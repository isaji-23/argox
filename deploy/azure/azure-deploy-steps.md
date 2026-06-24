# Argox on Azure — step-by-step deploy checklist

Ordered, copy-paste runbook to deploy the full stack to **Azure Container
Apps** with **Blob Storage** (span payloads) and an **Azure Files** share (the
DuckDB index). Run from `deploy/azure/`. Fill the variables once; the rest is
copy-paste.

> All commands use the Azure CLI. Auth is ON, so the Collector stays on
> **internal** ingress and only the Dashboard is public.

---

## 0. Prerequisites

```bash
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

## 1. Variables (edit these)

```bash
export RG=argox-rg
export LOC=westeurope
export ENV=argox-env
export ACR=argoxacr$RANDOM          # must be globally unique, lowercase
export STORAGE=argoxstg$RANDOM       # must be globally unique, lowercase
export TAG=v1
# Strong admin key (break-glass; mints the first API key):
export ADMIN_KEY=$(openssl rand -hex 32)
echo "SAVE THIS ADMIN KEY: $ADMIN_KEY"
```

## 2. Resource group

```bash
az group create -n $RG -l $LOC
```

## 3. Container registry + build images

```bash
az acr create -g $RG -n $ACR --sku Basic --admin-enabled true

# Build in the cloud (no local Docker needed). Paths are repo-relative:
az acr build -r $ACR -t argox-collector:$TAG ../../argox-project/argox-collector
az acr build -r $ACR -t argox-dashboard:$TAG ../../argox-dashboard
```

## 4. Storage: Blob container (payloads) + File share (DuckDB index)

```bash
az storage account create -g $RG -n $STORAGE --sku Standard_LRS --kind StorageV2

# Keys + connection string for the Collector:
export STG_KEY=$(az storage account keys list -g $RG -n $STORAGE --query "[0].value" -o tsv)
export STG_CONN=$(az storage account show-connection-string -g $RG -n $STORAGE -o tsv)

# Blob container for span batches / policies:
az storage container create --account-name $STORAGE --account-key $STG_KEY -n argox

# Azure Files share for the DuckDB index (5 GiB is plenty):
az storage share-rm create -g $RG --storage-account $STORAGE -n argox-index --quota 5
```

## 5. Container Apps environment

```bash
az containerapp env create -g $RG -n $ENV -l $LOC
```

### 5b. Register the Azure Files share with the environment

This is the persistent-volume definition the Collector mounts in step 7.

```bash
az containerapp env storage set -g $RG -n $ENV \
  --storage-name argox-index \
  --storage-type AzureFile \
  --azure-file-account-name $STORAGE \
  --azure-file-account-key $STG_KEY \
  --azure-file-share-name argox-index \
  --access-mode ReadWrite
```

## 6. Collector app (internal, single replica, secrets)

```bash
az containerapp create -g $RG -n collector \
  --environment $ENV \
  --image $ACR.azurecr.io/argox-collector:$TAG \
  --registry-server $ACR.azurecr.io \
  --ingress internal --target-port 8000 \
  --min-replicas 1 --max-replicas 1 \
  --cpu 0.5 --memory 1.0Gi \
  --secrets storage-conn="$STG_CONN" admin-key="$ADMIN_KEY" \
  --env-vars \
    ARGOX_STORAGE_BACKEND=azure \
    ARGOX_STORAGE_AZURE_CONNECTION_STRING=secretref:storage-conn \
    ARGOX_STORAGE_AZURE_CONTAINER=argox \
    ARGOX_INDEX_DUCKDB_PATH=/data/index.duckdb \
    ARGOX_AUTH_ENABLED=true \
    ARGOX_BOOTSTRAP_ADMIN_KEY=secretref:admin-key
```

> `--min-replicas 1 --max-replicas 1` is mandatory: DuckDB allows a single
> writer, so the Collector must never scale past one replica (COL-15 covers
> multi-replica). `--min 1` also stops scale-to-zero, which an internal-ingress
> app cannot recover from.

## 7. Mount the DuckDB volume on the Collector

The volume is attached by editing the app's YAML (the CLI has no one-liner).

```bash
az containerapp show -n collector -g $RG -o yaml > collector.yaml
```

Edit `collector.yaml` — under `properties.template`:

```yaml
    template:
      containers:
      - image: <acr>.azurecr.io/argox-collector:v1
        name: collector
        # ... existing resources/env ...
        volumeMounts:
        - volumeName: index-vol
          mountPath: /data           # ARGOX_INDEX_DUCKDB_PATH lives here
      volumes:
      - name: index-vol
        storageName: argox-index     # the env storage from step 5b
        storageType: AzureFile
```

Apply:

```bash
az containerapp update -n collector -g $RG --yaml collector.yaml
```

Verify the mount:

```bash
az containerapp exec -n collector -g $RG --command "ls -la /data"
# After some traffic you should see index.duckdb persist across revisions.
```

## 8. Dashboard app (external, public)

```bash
az containerapp create -g $RG -n dashboard \
  --environment $ENV \
  --image $ACR.azurecr.io/argox-dashboard:$TAG \
  --registry-server $ACR.azurecr.io \
  --ingress external --target-port 80 \
  --min-replicas 1 --max-replicas 3 \
  --env-vars COLLECTOR_UPSTREAM=http://collector

# Print the public URL:
az containerapp show -n dashboard -g $RG --query properties.configuration.ingress.fqdn -o tsv
```

`COLLECTOR_UPSTREAM=http://collector` makes the Dashboard's nginx proxy
same-environment to the Collector's internal ingress (port 80).

## 9. (Optional) Dashboard SSO with Microsoft Entra ID

Skip to run with API keys only. To enable JWT auth for dashboard users, add to
the **collector** app:

```bash
az containerapp update -n collector -g $RG --set-env-vars \
  ARGOX_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0 \
  ARGOX_OIDC_AUDIENCE=<app-registration-client-id> \
  ARGOX_OIDC_JWKS_URI=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys \
  ARGOX_OIDC_ADMIN_ROLE=<entra-app-role-for-admin>
```

(See `argox-project/docs/collector/auth.md`.)

## 10. Smoke test

```bash
FQDN=$(az containerapp show -n dashboard -g $RG --query properties.configuration.ingress.fqdn -o tsv)

# Health (no auth):
curl -s https://$FQDN/api/v1/../healthz   # or open https://$FQDN in a browser

# Mint a real API key with the break-glass admin key:
curl -s -X POST https://$FQDN/api/v1/keys \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"prod","scopes":["read","ingest"]}'

# Ingest the seed trace (through the Dashboard proxy):
curl -s -X POST https://$FQDN/v1/traces \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  --data @../docker/seed/trace.json

# Open the Dashboard — the trace should appear:
echo "https://$FQDN"
```

---

## Updating an existing deployment

ACA is revision-based: each change produces a new immutable revision and, in
single-revision mode (the default), traffic shifts to it once it is healthy.
Mounts, secrets and env vars are part of the app template, so they **carry over**
to new revisions — you only re-specify what changed.

Use a fresh, immutable tag every time (never reuse `latest`) so revisions and
rollbacks are traceable.

### Code change (new image)

```bash
export NEWTAG=v2

# Rebuild only the service that changed (or both):
az acr build -r $ACR -t argox-collector:$NEWTAG ../../argox-project/argox-collector
az acr build -r $ACR -t argox-dashboard:$NEWTAG ../../argox-dashboard

# Roll the app(s) to the new image — creates a new revision:
az containerapp update -n collector -g $RG --image $ACR.azurecr.io/argox-collector:$NEWTAG
az containerapp update -n dashboard -g $RG --image $ACR.azurecr.io/argox-dashboard:$NEWTAG
```

### Config / secret change (no rebuild)

```bash
# Env var:
az containerapp update -n collector -g $RG --set-env-vars ARGOX_LOG_LEVEL=DEBUG

# Secret value (e.g. rotate the admin key) — then bump a revision to pick it up:
az containerapp secret set -n collector -g $RG --secrets admin-key="$(openssl rand -hex 32)"
az containerapp update -n collector -g $RG
```

### Volume / template change

Re-export the YAML, edit, re-apply (same as step 7):

```bash
az containerapp show -n collector -g $RG -o yaml > collector.yaml
# edit...
az containerapp update -n collector -g $RG --yaml collector.yaml
```

### Rollback

Immutable tags make rollback a re-deploy of the previous image:

```bash
az containerapp revision list -n collector -g $RG -o table   # see history
az containerapp update -n collector -g $RG --image $ACR.azurecr.io/argox-collector:v1
```

> **DuckDB and the revision swap.** During a Collector update the new revision's
> replica starts while the old one may still be running, so two processes can
> briefly hold the same DuckDB file on the share. DuckDB's file lock serializes
> them — the new replica may log a lock error and retry until the old revision
> is deactivated. For a clean swap, deactivate the old revision first:
> ```bash
> az containerapp revision list -n collector -g $RG -o table
> az containerapp revision deactivate -n collector -g $RG --revision <old-revision>
> ```
> The Dashboard has no such constraint (stateless) and updates with zero
> downtime.

## What you deployed (recap)

| Resource | Name | Role |
|---|---|---|
| Resource group | `$RG` | container for everything |
| Container registry | `$ACR` | hosts the two images |
| Storage account | `$STORAGE` | blob container `argox` (payloads) + file share `argox-index` (DuckDB) |
| ACA environment | `$ENV` | runs both apps, holds the storage definition |
| Collector app | `collector` | internal ingress, 1 replica, `/data` = Azure Files |
| Dashboard app | `dashboard` | external ingress, public URL, nginx proxy |

## Gotchas

- **DuckDB on Azure Files (SMB):** fine for a single writer (one replica). Do
  not raise `--max-replicas`; concurrent writers will corrupt the index.
- **Keep the Collector internal.** It has no rate limiting; the public surface
  is only the Dashboard.
- **Managed Identity for Blob is not supported yet** — the connection string is
  the only path until the storage backend learns `DefaultAzureCredential`.
- **Cost:** scale the Dashboard to 0 when idle (`--min-replicas 0`) to save; the
  Collector must stay at 1.

## Teardown

```bash
az group delete -n $RG --yes --no-wait
```
