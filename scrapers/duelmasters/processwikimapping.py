
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from dotenv import load_dotenv
from service.mongo_service import MongoService

load_dotenv()
mongo_service = MongoService()

class ProcessWikiMapping:
    def getAllCardForBooster(self, booster):
        """
        Get all card IDs for a given booster ID.
        
        Args:
            booster_id (str): The ID of the booster (e.g., "dm25ex4")
        
        Returns:
            list: A list of card IDs found in the booster
        """
        return mongo_service.find_all_by_field("CL_duelmasters","booster",booster)
    
    def extractUniqueWikiLinksFromCards(self, cards: list) -> set:
        """
        Extract unique wiki links from a list of card documents.
        Also includes wiki links from the 'awaken' field.
        
        Args:
            cards (list): A list of card documents from MongoDB
        
        Returns:
            set: A set of unique wiki URLs
        """
        unique_links = set()
        for card in cards:
            # Get main wiki URL
            wiki_url = card.get('wikiurl')
            if wiki_url:
                unique_links.add(wiki_url)
            
            # Get wiki URLs from awaken field
            awaken = card.get('awaken', [])
            if awaken and isinstance(awaken, list):
                for awaken_card in awaken:
                    awaken_url = awaken_card.get('wikiurl')
                    if awaken_url:
                        unique_links.add(awaken_url)
        
        print(f"✅ Extracted {len(unique_links)} unique wiki links from {len(cards)} cards (including awakened forms).")
        return unique_links
    
    def getCardsFromWikiUrls(self, wiki_urls: set) -> list:
        """
        Query MongoDB to find all documents matching the given wiki URLs.
        
        Args:
            wiki_urls (set): A set of unique wiki URLs to search for
        
        Returns:
            list: A list of card documents matching the wiki URLs
        """
        if not wiki_urls:
            print("⚠️  No wiki URLs provided")
            return []
        
        try:
            # Convert set to list for MongoDB query
            url_list = list(wiki_urls)
            
            # Query MongoDB using the new find_all_by_field_array method
            matching_cards = mongo_service.find_all_by_field_array("CL_duelmasters_wiki", "url", url_list)
            
            return matching_cards
        
        except Exception as e:
            print(f"❌ Error querying MongoDB: {e}")
            return []
    
    def load_wiki_data_from_mongodb(self) -> list:
        """Load wiki scraped data directly from MongoDB CL_duelmaster_wiki collection"""
        try:
            wiki_cards = mongo_service.find_all("CL_duelmaster_wiki", {})
            print(f"✅ Loaded {len(wiki_cards)} wiki scraped cards from MongoDB")
            return wiki_cards
        except Exception as e:
            print(f"❌ Error loading wiki data from MongoDB: {e}")
            return []
    
    def update_card_with_wiki_data(self, card_doc: dict, wiki_card: dict, wiki_map: dict = None) -> dict:
        """
        Update a card document with wiki scraped data.
        
        For main card: update cardName, type, effects
        For twinpact: update cardName2, type2, effects2
        For awaken: backup JP fields then update with wiki data (using awaken's own wikiurl)
        
        Args:
            card_doc: Original card document from CL_duelmasters
            wiki_card: Wiki scraped card data from CL_duelmaster_wiki
            wiki_map: Optional dict mapping wikiurl to wiki card for awaken lookups
        
        Returns:
            dict: Updated card document
        """
        cards = wiki_card.get('cards', [])
        
        if not cards:
            return card_doc
        
        # Update first card form
        if len(cards) > 0:
            card_0 = cards[0]
            card_doc['cardName'] = card_0.get('name')
            card_doc['type'] = card_0.get('card_type')
            card_doc['effects'] = card_0.get('english_text')
        
        # Update second card form if twinpact
        if len(cards) > 1:
            card_1 = cards[1]
            card_doc['cardName2'] = card_1.get('name')
            card_doc['type2'] = card_1.get('card_type')
            card_doc['effects2'] = card_1.get('english_text')
        
        # Update awaken forms if they exist
        awaken = card_doc.get('awaken', [])
        if awaken and isinstance(awaken, list):
            for awaken_card in awaken:
                # Get the awaken card's own wikiurl
                awaken_url = awaken_card.get('wikiurl')
                
                # First back up current values to JP fields
                awaken_card['cardNameJP'] = awaken_card.get('cardName')
                awaken_card['raceJP'] = awaken_card.get('race')
                awaken_card['effectsJP'] = awaken_card.get('effect')
                
                # Look up matching wiki card using awaken's wikiurl
                if wiki_map and awaken_url and awaken_url in wiki_map:
                    awaken_wiki = wiki_map[awaken_url]
                    awaken_cards = awaken_wiki.get('cards', [])
                    
                    if awaken_cards:
                        wiki_form = awaken_cards[0]  # Use first form
                        awaken_card['cardName'] = wiki_form.get('name')
                        awaken_card['type'] = wiki_form.get('card_type')
                        awaken_card['race'] = wiki_form.get('race')
                        awaken_card['effect'] = wiki_form.get('english_text')
        
        return card_doc
    
if __name__ == "__main__":
    booster_id = "dm25ex4"
    processor = ProcessWikiMapping()
    
    # Step 1: Get all cards for the booster
    print(f"🚀 Getting all cards for booster: {booster_id}\n")
    listofcards = processor.getAllCardForBooster(booster_id)
    print(f"📊 Found {len(listofcards)} cards\n")
    
    # Step 2: Extract unique wiki links
    print("🔗 Extracting unique wiki links...\n")
    unique_wiki_links = processor.extractUniqueWikiLinksFromCards(listofcards)
    
    # Display the wiki links
    print("\n📋 Unique Wiki Links:")
    print("=" * 80)
    for link in sorted(unique_wiki_links):
        print(f"  {link}")
    
    # Step 3: Query MongoDB for documents matching the wiki URLs
    print("\n🔍 Querying MongoDB for matching documents...\n")
    matching_cards = processor.getCardsFromWikiUrls(unique_wiki_links)
    print(f"📊 Retrieved {len(matching_cards)} documents from MongoDB\n")
    
    # Display summary
    print("=" * 80)
    print("📋 MATCHING DOCUMENTS SUMMARY")
    print("=" * 80)
    for card in matching_cards:
        url = card.get('url', 'N/A')
        is_twinpact = card.get('is_twinpact', False)
        cards = card.get('cards', [])
        
        print(f"\n🔗 {url}")
        print(f"   Twin Pact: {'✅ Yes' if is_twinpact else '❌ No'}")
        print(f"   Forms: {len(cards)}")
        
        for idx, form in enumerate(cards, 1):
            name = form.get('name', 'N/A')
            card_type = form.get('card_type', 'N/A')
            civ = form.get('civilization', 'N/A')
            
            print(f"\n   Form {idx}:")
            print(f"     Name: {name}")
            print(f"     Type: {card_type}")
            print(f"     Civilization: {civ}")
            
            english_text = form.get('english_text', '')
            if english_text:
                lines = english_text.split('\n')
                print(f"     Effects ({len(lines)} lines):")
                for line in lines[:3]:  # Show first 3 lines
                    print(f"       ▪ {line[:70]}...")
    
    print("\n" + "=" * 80)
    print(f"✅ Processing complete: {len(matching_cards)} wiki cards retrieved")
    print("=" * 80)
    
    # Step 4: Update listofcards with wiki data
    print("\n🔄 Updating cards with wiki data...\n")
    
    # Create a mapping of wiki URLs to wiki cards for quick lookup
    wiki_map = {card.get('url'): card for card in matching_cards}
    
    print(f"📊 Wiki Map Statistics:")
    print(f"   Total cards in booster: {len(listofcards)}")
    print(f"   Unique wiki URLs found: {len(wiki_map)}")
    print(f"   Wiki scraped cards available: {len(matching_cards)}\n")
    
    updated_count = 0
    not_matched = []
    no_wiki_url = []
    
    for card in listofcards:
        wiki_url = card.get('wikiurl')
        
        if not wiki_url:
            no_wiki_url.append(card.get('cardName', 'Unknown'))
            continue
        
        if wiki_url and wiki_url in wiki_map:
            wiki_card = wiki_map[wiki_url]
            # Pass wiki_map so awaken cards can be looked up by their own wikiurl
            processor.update_card_with_wiki_data(card, wiki_card, wiki_map)
            updated_count += 1
        else:
            not_matched.append((card.get('cardName', 'Unknown'), wiki_url))
    
    print(f"✅ Updated: {updated_count} cards")
    print(f"❌ No wiki URL: {len(no_wiki_url)} cards")
    print(f"❌ Wiki URL not found: {len(not_matched)} cards\n")
    
    if no_wiki_url:
        print("Cards with NO wiki URL:")
        for name in no_wiki_url[:10]:  # Show first 10
            print(f"  • {name}")
        if len(no_wiki_url) > 10:
            print(f"  ... and {len(no_wiki_url) - 10} more\n")
    
    if not_matched:
        print("Cards with UNMATCHED wiki URLs:")
        for name, url in not_matched[:10]:  # Show first 10
            print(f"  • {name}")
            print(f"    URL: {url}")
        if len(not_matched) > 10:
            print(f"  ... and {len(not_matched) - 10} more\n")
    
    print(f"✅ Updated {updated_count} cards with wiki data\n")
    
    # Display updated cards
    print("=" * 80)
    print("📋 UPDATED CARDS SUMMARY")
    print("=" * 80)
    for idx, card in enumerate(listofcards[:5], 1):  # Show first 5
        print(f"\n{idx}. {card.get('cardName', 'N/A')}")
        print(f"   Type: {card.get('type', 'N/A')}")
        print(f"   Effects (first 100 chars): {card.get('effects', 'N/A')[:100]}...")
        
        if card.get('cardName2'):
            print(f"   Form 2: {card.get('cardName2')}")
            print(f"   Type 2: {card.get('type2', 'N/A')}")
    
    print("\n" + "=" * 80)
    print(f"✅ Complete! {updated_count}/{len(listofcards)} cards updated")
    print("=" * 80)
    
    # Step 5: Save and display final results
    print("\n📋 FINAL RESULTS FOR VALIDATION")
    print("=" * 80)
    
    import json
    
    # Save to file for validation
    output_file = "wiki_updated_cards.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(listofcards, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Full results saved to: {output_file}\n")
    
    # Display detailed summary of first 3 cards
    print("DETAILED VIEW (First 3 cards):")
    print("=" * 80)
    
    for idx, card in enumerate(listofcards[:3], 1):
        print(f"\n{'='*80}")
        print(f"CARD {idx}: {card.get('cardName', 'N/A')}")
        print(f"{'='*80}")
        
        # Main card info
        print(f"\n📌 MAIN FORM:")
        print(f"  cardName: {card.get('cardName', 'N/A')}")
        print(f"  cardUid: {card.get('cardUid', 'N/A')}")
        print(f"  type: {card.get('type', 'N/A')}")
        print(f"  civilization: {card.get('civilization', 'N/A')}")
        print(f"  power: {card.get('power', 'N/A')}")
        print(f"  cost: {card.get('cost', 'N/A')}")
        print(f"  race: {card.get('race', 'N/A')}")
        print(f"  illustrator: {card.get('illustrator', 'N/A')}")
        
        effects = card.get('effects', '')
        if effects:
            lines = effects.split('\n')
            print(f"  effects ({len(lines)} lines):")
            for line in lines[:2]:
                print(f"    • {line[:75]}")
        
        # Twin pact form if exists
        if card.get('cardName2'):
            print(f"\n📌 TWINPACT FORM 2:")
            print(f"  cardName2: {card.get('cardName2', 'N/A')}")
            print(f"  type2: {card.get('type2', 'N/A')}")
            print(f"  civilization2: {card.get('civilization2', 'N/A')}")
            print(f"  power2: {card.get('power2', 'N/A')}")
            
            effects2 = card.get('effects2', '')
            if effects2:
                lines = effects2.split('\n')
                print(f"  effects2 ({len(lines)} lines):")
                for line in lines[:2]:
                    print(f"    • {line[:75]}")
        
        # Awaken forms if exist
        awaken = card.get('awaken', [])
        if awaken:
            print(f"\n📌 AWAKENED FORMS ({len(awaken)}):")
            for aw_idx, aw_card in enumerate(awaken, 1):
                print(f"\n  Awaken {aw_idx}:")
                print(f"    cardName: {aw_card.get('cardName', 'N/A')}")
                print(f"    cardNameJP: {aw_card.get('cardNameJP', 'N/A')}")
                print(f"    type: {aw_card.get('type', 'N/A')}")
                print(f"    race: {aw_card.get('race', 'N/A')}")
                print(f"    raceJP: {aw_card.get('raceJP', 'N/A')}")
                
                effect = aw_card.get('effect', '')
                if effect:
                    print(f"    effect (first 100 chars): {effect[:100]}...")
                
                effectsJP = aw_card.get('effectsJP', '')
                if effectsJP:
                    print(f"    effectsJP (first 100 chars): {effectsJP[:100]}...")
    
    print("\n" + "=" * 80)
    print(f"SUMMARY:")
    print(f"  Total Cards: {len(listofcards)}")
    print(f"  Cards Updated: {updated_count}")
    print(f"  Save Location: {output_file}")
    print("=" * 80)



