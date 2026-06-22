from dotenv import load_dotenv; load_dotenv()
from api_clients.github import graphql_query, _DISCOVER_REPOS_QUERY

cursor = None
total = 0
while True:
    data = graphql_query(_DISCOVER_REPOS_QUERY, {'org': 'microsoft', 'cursor': cursor})
    page = data['organization']['repositories']
    total += len(page['nodes'])
    print(f'{total} repos so far...')
    if not page['pageInfo']['hasNextPage']:
        break
    cursor = page['pageInfo']['endCursor']
print('Done!')