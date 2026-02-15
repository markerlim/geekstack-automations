
from service.mongo_service import MongoService

mongo_service = MongoService()

class ProcessWikiMapping:
    def getListOfWikiLinksForBooster(self, booster_id):
        """
        Get all wiki links for a given booster ID.
        
        Args:
            booster_id (str): The ID of the booster (e.g., "dm25ex4")
        
        Returns:
            dict: A mapping of card IDs to their corresponding wiki URLs
        """
        return mongo_service.find_all_by_field("CL_duelmasters_wiki","url")
    
    def getAllCardIDsForBooster(self, booster_id):
        """
        Get all card IDs for a given booster ID.
        
        Args:
            booster_id (str): The ID of the booster (e.g., "dm25ex4")
        
        Returns:
            list: A list of card IDs found in the booster
        """
        wiki_links = self.getListOfWikiLinksForBooster(booster_id)
        return list(wiki_links.keys())

if __name__ == "__main__":
    booster_id = "dm25ex4"
    processor = ProcessWikiMapping()
    card_mapping = processor.getListOfWikiLinksForBooster(booster_id)
    
    print(f"Total cards found for booster {booster_id}: {len(card_mapping)}")
    print("=" * 80)
    
    # Display the first 5 card mappings
    for i, (card_id, wiki_url) in enumerate(list(card_mapping.items())[:5], 1):
        print(f"{i}. Card ID: {card_id}")
        print(f"   Wiki URL: {wiki_url}\n")