main()
  ├─ Initialize YuyuTeiScraper (Selenium + MongoDB)
  ├─ scrape_single_card_links()
  │  ├─ Navigate to https://yuyu-tei.jp/top/ua
  │  ├─ Click accordion button (.accordion-button.text-primary) to expand menu
  │  ├─ extract_all_links()
  │  │  ├─ Find #side-sell-single container (expanded menu)
  │  │  ├─ Find all divs with class "accordion-item rounded-0 mb-2 sub-child corner"
  │  │  ├─ Extract href from onclick attributes (location.href='URL')
  │  │  └─ Store in self.all_hrefs list
  │  │
  │  └─ scrape_cards_from_links()
  │     ├─ For each extracted link:
  │     │  ├─ Navigate to that category URL
  │     │  ├─ extract_cardlist_data()
  │     │  │  ├─ Find all div.py-4.cards-list sections (rarity groupings)
  │     │  │  ├─ For each rarity section:
  │     │  │  │  ├─ Extract rarity from h3 span
  │     │  │  │  ├─ Find all div.card-product.position-relative.mt-4
  │     │  │  │  └─ For each card extract:
  │     │  │  │     ├─ card_id (from span with border)
  │     │  │  │     ├─ card_name (from h4.text-primary)
  │     │  │  │     ├─ product_link (from parent <a> href) ← UNIQUE KEY
  │     │  │  │     ├─ price (from strong.d-block.text-end)
  │     │  │  │     └─ stock (from label.form-check-label)
  │     │  │  │
  │     │  │  ├─ Create card_entry with price_history
  │     │  │  └─ Append to self.cardlist_data
  │     │  │
  │     │  └─ Wait 1.5 seconds before next link
  │     └─ Continue until all links processed
  │
  ├─ save_backup()
  │  ├─ Create timestamp (YYYYMMDD_HHMMSS)
  │  ├─ Save self.cardlist_data to yuyuteidb/yuyutei_cardlist_backup_{timestamp}.json
  │  └─ Return backup filepath
  │
  ├─ upload_to_mongo(db='geekstack', collection='cardprices_yyt')
  │  ├─ Query MongoDB for existing product_links
  │  ├─ Separate cards into:
  │  │  ├─ NEW CARDS (product_link not in database)
  │  │  └─ EXISTING CARDS (product_link already exists)
  │  │
  │  ├─ BULK INSERT all new cards at once
  │  │  └─ Set created_at & last_updated timestamps
  │  │
  │  ├─ BULK UPDATE all existing cards
  │  │  ├─ Query by product_link
  │  │  ├─ Find existing price_history
  │  │  ├─ Merge: new timestamps + old timestamps
  │  │  ├─ Update all fields + merged price_history
  │  │  └─ Update last_updated timestamp
  │  │
  │  └─ Return success/failure
  │
  └─ If upload fails:
     └─ Print backup location (data is safe, can retry later)