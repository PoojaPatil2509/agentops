"""
Sample prompts for synthetic agents.

These are realistic-looking inputs for three personas:
- SupportBot answers product/support questions
- ResearchAgent answers technical/research queries
- CodeReviewer reviews short Python snippets

Adding more prompts increases traffic variety without code changes.
"""

SUPPORT_QUESTIONS = [
    "How do I export my data as CSV?",
    "My dashboard is showing yesterday's numbers, not today's. Help?",
    "Can I invite teammates to my workspace?",
    "What's the difference between the Pro and Enterprise plans?",
    "How do I reset my password? The reset email isn't arriving.",
    "Is there an API I can use to pull metrics into our internal tools?",
    "The mobile app keeps crashing on Android 14. Is there a fix?",
    "Can I cancel my subscription mid-month and get a prorated refund?",
    "Why is my chart showing 'No data available' for the last 6 hours?",
    "How do I set up SSO with Okta for my team?",
]

RESEARCH_QUERIES = [
    "What are the tradeoffs between Apache Iceberg and Apache Hudi for streaming workloads?",
    "Compare the cost-effectiveness of AWS Glue vs running Spark on EMR.",
    "How does Kinesis Data Streams differ from MSK for sub-second-latency use cases?",
    "What are emerging best practices for observability of LLM-powered agents in 2026?",
    "Summarize the main critiques of the medallion architecture pattern.",
    "When is DynamoDB a better choice than Aurora Serverless v2 for a multi-tenant SaaS?",
    "What's the practical difference between Lambda provisioned concurrency and SnapStart?",
]

CODE_SNIPPETS = [
    "def get_user(id):\n    return db.query(f'SELECT * FROM users WHERE id = {id}')",
    "for i in range(len(items)):\n    process(items[i])",
    "try:\n    result = call_api()\nexcept:\n    pass",
    "passwords = open('passwords.txt').read().split('\\n')",
    "import requests\nresponse = requests.get(URL, verify=False)",
    "def add_item(item, items=[]):\n    items.append(item)\n    return items",
    "with open('big.csv') as f:\n    data = f.read()\n    rows = data.split('\\n')",
]