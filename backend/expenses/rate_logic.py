def get_exchange_rate(currency):
    # Check if the user specified a rate
    if currency in user_specified_rates:
        return user_specified_rates[currency]
    else:
        # Fetch the latest rates from the database or file
        return latest_rates[currency]  # Assuming latest_rates is a dictionary with the latest rates
