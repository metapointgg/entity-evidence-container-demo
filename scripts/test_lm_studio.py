from eec.local_llm import expand_search_query, list_models, summarise_search_results

print("Available models:")
for model in list_models():
    print(f"- {model}")

print("\nExpanded search terms:")
for term in expand_search_query("where did the customer money come from?"):
    print(f"- {term}")

print("\nSummary test:")
print(
    summarise_search_results(
        "where did the customer money come from?",
        [
            {
                "entity_id": "CUST-000001",
                "object_id": "DOC-000001",
                "category": "Due Diligence",
                "document_type": "Source of Wealth Review",
                "source_system": "AML Platform",
                "filename": "source_of_wealth_review.pdf",
                "search_text": "The customer declared investment income and proceeds from a property sale. Supporting bank statements and sale documentation were requested.",
            }
        ],
    )
)
