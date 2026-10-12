from app.routes.real_data import get_cached_loader, _DISABLE_DATASET_LOOKUPS
print("DISABLE_DATASET_LOOKUPS:", _DISABLE_DATASET_LOOKUPS)
loader = get_cached_loader()
print("Loader type:", type(loader))
print("Accounts:", len(loader.accounts) if hasattr(loader, 'accounts') else 'N/A')
print("Towns:", len(loader.towns) if hasattr(loader, 'towns') else 'N/A')
print("Import and load successful!")