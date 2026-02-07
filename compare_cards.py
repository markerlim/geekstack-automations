import json
from typing import List, Dict, Tuple

def compare_card_collections(wiki_results_path: str, dmfull_path: str) -> Dict:
    """
    Compare two JSON card collections to find missing cards by ID.
    
    Args:
        wiki_results_path: Path to wiki_results.json
        dmfull_path: Path to dmfull.json
    
    Returns:
        Dictionary containing:
        - missing_in_dmfull: Cards in wiki_results but not in dmfull
        - extra_in_dmfull: Cards in dmfull but not in wiki_results
        - stats: Statistics about the comparison
    """
    
    # Load JSON files
    with open(wiki_results_path, 'r', encoding='utf-8') as f:
        wiki_results = json.load(f)
    
    with open(dmfull_path, 'r', encoding='utf-8') as f:
        dmfull = json.load(f)
    
    # Create dictionaries mapping _id to full card object
    wiki_ids = {card["_id"]["$oid"]: card for card in wiki_results}
    dmfull_ids = {card["_id"]["$oid"]: card for card in dmfull}
    
    # Find missing cards
    missing_in_dmfull = []
    for oid, card in wiki_ids.items():
        if oid not in dmfull_ids:
            missing_in_dmfull.append(card)
    
    # Find extra cards (in dmfull but not in wiki_results)
    extra_in_dmfull = []
    for oid, card in dmfull_ids.items():
        if oid not in wiki_ids:
            extra_in_dmfull.append(card)
    
    # Statistics
    stats = {
        "wiki_results_total": len(wiki_results),
        "dmfull_total": len(dmfull),
        "missing_in_dmfull_count": len(missing_in_dmfull),
        "extra_in_dmfull_count": len(extra_in_dmfull),
        "matching_ids": len(wiki_ids) - len(missing_in_dmfull)
    }
    
    return {
        "missing_in_dmfull": missing_in_dmfull,
        "extra_in_dmfull": extra_in_dmfull,
        "stats": stats
    }


def print_comparison_report(comparison_result: Dict):
    """Print a formatted report of the comparison results."""
    stats = comparison_result["stats"]
    
    print("\n" + "="*60)
    print("CARD COLLECTION COMPARISON REPORT")
    print("="*60)
    
    print(f"\nStatistics:")
    print(f"  Wiki Results Total:        {stats['wiki_results_total']}")
    print(f"  DM Full Total:             {stats['dmfull_total']}")
    print(f"  Matching IDs:              {stats['matching_ids']}")
    print(f"  Missing in dmfull:         {stats['missing_in_dmfull_count']}")
    print(f"  Extra in dmfull:           {stats['extra_in_dmfull_count']}")
    
    # Print missing cards
    if comparison_result["missing_in_dmfull"]:
        print(f"\n\nMISSING IN dmfull.json ({len(comparison_result['missing_in_dmfull'])} cards):")
        print("-" * 60)
        for card in comparison_result["missing_in_dmfull"]:
            print(f"  ID: {card['_id']['$oid']}")
            print(f"  Name: {card.get('cardName', 'N/A')}")
            print(f"  Card ID: {card.get('cardId', 'N/A')}")
            print()
    
    # Print extra cards
    if comparison_result["extra_in_dmfull"]:
        print(f"\n\nEXTRA IN dmfull.json ({len(comparison_result['extra_in_dmfull'])} cards):")
        print("-" * 60)
        for card in comparison_result["extra_in_dmfull"]:
            print(f"  ID: {card['_id']['$oid']}")
            print(f"  Name: {card.get('cardName', 'N/A')}")
            print(f"  Card ID: {card.get('cardId', 'N/A')}")
            print()


def export_missing_cards(comparison_result: Dict, output_path: str):
    """Export missing cards to a JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(comparison_result["missing_in_dmfull"], f, indent=2, ensure_ascii=False)
    print(f"\nExported {len(comparison_result['missing_in_dmfull'])} missing cards to {output_path}")


def export_extra_cards(comparison_result: Dict, output_path: str):
    """Export extra cards to a JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(comparison_result["extra_in_dmfull"], f, indent=2, ensure_ascii=False)
    print(f"\nExported {len(comparison_result['extra_in_dmfull'])} extra cards to {output_path}")


if __name__ == "__main__":
    # Run comparison
    result = compare_card_collections(
        "wiki_results.json",
        "dmfull.json"
    )
    
    # Print report
    print_comparison_report(result)
    
    # Optionally export missing cards
    if result["missing_in_dmfull"]:
        export_missing_cards(result, "missing_cards.json")
    
    # Optionally export extra cards
    if result["extra_in_dmfull"]:
        export_extra_cards(result, "extra_cards.json")
