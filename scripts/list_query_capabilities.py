from eec.query_interpreter import query_capability_matrix

for key, value in query_capability_matrix().items():
    print(f"{key}")
    print(f"  intent: {value.get('intent')}")
    print(f"  result_type: {value.get('result_type')}")
    print(f"  requires_selected_entity: {value.get('requires_selected_entity')}")
    print(f"  filters: {', '.join(value.get('supports_filters', []))}")
    print(f"  description: {value.get('description')}")
    print()
