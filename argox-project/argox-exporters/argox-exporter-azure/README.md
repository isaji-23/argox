# argox-exporter-azure

Azure Blob Storage exporter for Argox OpenTelemetry spans.

## Usage considerations

### Async and Batching
Each `export()` call makes a synchronous HTTP PUT request to Azure Blob Storage to create a new JSONL blob. If you use `SimpleSpanProcessor` in production, this will block the thread for every span. It is strongly recommended to use `BatchSpanProcessor` instead to aggregate spans and minimize the number of API calls, which also helps control Azure Storage costs (as you pay per PUT operation).

### Container validation
This exporter does not automatically create the Azure Blob Storage container or validate its existence upon initialization. You must ensure the target container exists before exporting spans, otherwise spans will fail to upload without crashing the application (though errors will be logged).

### Security
The exporter requires a connection string. Do not hardcode your connection string in plain text within your codebase. It is recommended to inject it via environment variables or securely retrieve it at runtime using Azure Key Vault.
