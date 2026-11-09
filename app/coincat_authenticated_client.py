"""SDK construction only; no legacy broker/controller imports or retry changes."""
def client_from_credentials(credentials):
    from coinbase.rest import RESTClient
    return RESTClient(api_key=credentials['name'],api_secret=credentials['privateKey'],timeout=15,verbose=False)
