import requests

def search_ticker(query):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=5&newsCount=0"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers)
        data = r.json()
        return [{"symbol": q['symbol'], "name": q.get('shortname', q.get('longname', ''))} for q in data.get('quotes', [])]
    except Exception as e:
        return []

print(search_ticker("TCS"))
