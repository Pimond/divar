#!/usr/bin/env python3
import requests
import json
import time
import random
import csv
import sys
import os

# Set up headers and cookies as provided by the working configuration
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json",
    "origin": "https://divar.ir",
    "referer": "https://divar.ir/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "x-render-type": "CSR",
    "x-standard-divar-error": "true",
}

COOKIES = {
    "did": "17ce261b-26bf-41cd-a27b-d3bf422c8b78",
    "city": "tehran",
}

def fa_to_en_digits(text):
    """Converts Persian and Arabic digits in a string to English digits."""
    if not isinstance(text, str):
        return text
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    english_digits = "0123456789"
    
    translation_table = str.maketrans(
        persian_digits + arabic_digits,
        english_digits + english_digits
    )
    return text.translate(translation_table)

def normalize_farsi_string(text):
    """Normalizes Farsi text by removing all spaces, ZWNJs, and converting Arabic characters."""
    if not isinstance(text, str):
        return ""
    # Arabic to Persian characters
    text = text.replace("ي", "ی").replace("ك", "ک")
    # Remove all spaces and ZWNJs
    for char in [" ", "\u200c", "\u200b", "\xa0"]:
        text = text.replace(char, "")
    return text.strip()

def parse_price(price_str):
    """Extracts numeric price as integer from Persian price string."""
    if not price_str:
        return None
    price_str = fa_to_en_digits(price_str)
    # Remove commas, spaces, and non-digit characters
    digits = "".join([c for c in price_str if c.isdigit()])
    if digits:
        return int(digits)
    return None

def parse_floor(floor_str):
    """Parses floor string (e.g. '۱ از ۴' or 'همکف') into (floor, total_floors)."""
    if not floor_str:
        return "", ""
    floor_str = fa_to_en_digits(floor_str).strip()
    
    # Check if we have "از" (of)
    if "از" in floor_str:
        parts = floor_str.split("از")
        floor_part = parts[0].strip()
        total_part = parts[1].strip()
        return floor_part, total_part
    
    # Special cases
    if "همکف" in floor_str:
        return "0", ""
    if "زیرهمکف" in floor_str:
        return "-1", ""
        
    return floor_str, ""

def extract_features(widgets):
    """Extracts elevator, parking, and storage features from widgets list."""
    elevator = "No"
    parking = "No"
    storage = "No"
    
    for widget in widgets:
        w_type = widget.get("widget_type")
        w_data = widget.get("data", {})
        
        if w_type == "GROUP_FEATURE_ROW":
            items = w_data.get("items", [])
            for item in items:
                title = item.get("title", "")
                available = item.get("available", False)
                val = "Yes" if available else "No"
                if "آسانسور" in title:
                    elevator = val
                elif "پارکینگ" in title:
                    parking = val
                elif "انباری" in title:
                    storage = val
    return elevator, parking, storage

def extract_group_info(widgets):
    """Extracts area_m2, year_built, and rooms from widgets list."""
    area_m2 = None
    year_built = None
    rooms = None
    
    for widget in widgets:
        w_type = widget.get("widget_type")
        w_data = widget.get("data", {})
        
        if w_type == "GROUP_INFO_ROW":
            items = w_data.get("items", [])
            for item in items:
                title = item.get("title", "")
                val_str = item.get("value", "")
                val_en = fa_to_en_digits(val_str)
                
                # Extract digits
                try:
                    val = int("".join([c for c in val_en if c.isdigit()]))
                except ValueError:
                    val = None
                    
                if "متراژ" in title:
                    area_m2 = val
                elif "ساخت" in title:
                    year_built = val
                elif "اتاق" in title:
                    rooms = val
    return area_m2, year_built, rooms

def fetch_post_details(session, token, post_date_fallback="", city_fallback="", category_fallback=""):
    """Fetches details for a single post token and returns a structured dict."""
    url = f"https://api.divar.ir/v8/posts-v2/web/{token}"
    try:
        r = session.get(url, headers=HEADERS, cookies=COOKIES, timeout=10)
        if r.status_code != 200:
            return None
        
        data = r.json()
        sections = data.get("sections", [])
        all_widgets = []
        for s in sections:
            all_widgets.extend(s.get("widgets", []))
            
        # Title and District from SEO
        seo = data.get("seo", {})
        title = seo.get("web_info", {}).get("title", "")
        district = seo.get("web_info", {}).get("district_persian", "")
        
        # Fallbacks or cleanups
        title = fa_to_en_digits(title)
        district = fa_to_en_digits(district)
        
        # Extract City
        city_data = data.get("city", {})
        city_name = city_data.get("name", "")
        if not city_name:
            city_name = seo.get("web_info", {}).get("city_persian", "")
        if not city_name:
            city_name = city_fallback or "تهران"
        city_name = fa_to_en_digits(city_name)
        
        # Extract Category
        category_slug = data.get("webengage", {}).get("category", "")
        if not category_slug:
            category_slug = category_fallback or "apartment-sell"
        
        # Extract Group Info Fields
        area_m2, year_built, rooms = extract_group_info(all_widgets)
        
        # Calculate Age based on shamsi calendar (we're in year 1405, shamsi)
        age = None
        if year_built is not None:
            if 1300 <= year_built <= 1405:
                age = 1405 - year_built
            elif year_built > 1900:  # Gregorian safety check
                age = max(0, 2026 - year_built)
            else:
                age = 0
        
        # Extract Authentic Photos
        authentic_photos = "N/A"
        for w in all_widgets:
            w_type = w.get("widget_type")
            w_data = w.get("data", {})
            if w_type == "UNEXPANDABLE_ROW":
                t = w_data.get("title", "")
                val = w_data.get("value", "")
                if "همین ملک" in t:
                    if "بله" in val:
                        authentic_photos = "Yes"
                    elif "خیر" in val:
                        authentic_photos = "No"
                    break

        # Extract Prices
        total_price_tomans = None
        price_per_m2_tomans = None
        
        for w in all_widgets:
            w_type = w.get("widget_type")
            w_data = w.get("data", {})
            if w_type == "UNEXPANDABLE_ROW":
                t = w_data.get("title", "")
                val = w_data.get("value", "")
                if "قیمت کل" in t:
                    total_price_tomans = parse_price(val)
                elif "قیمت هر متر" in t:
                    price_per_m2_tomans = parse_price(val)
                    
        # Extract Floor & Total Floors
        floor = ""
        total_floors = ""
        for w in all_widgets:
            w_type = w.get("widget_type")
            w_data = w.get("data", {})
            if w_type == "UNEXPANDABLE_ROW":
                t = w_data.get("title", "")
                val = w_data.get("value", "")
                if "طبقه" in t:
                    floor, total_floors = parse_floor(val)
                    break
                    
        # Extract features
        elevator, parking, storage = extract_features(all_widgets)
        
        # Calculate millions values
        total_price_mtomans = None
        if total_price_tomans is not None:
            total_price_mtomans = round(total_price_tomans / 1000000.0, 2)
            
        price_per_m2_mtomans = None
        if price_per_m2_tomans is not None:
            price_per_m2_mtomans = round(price_per_m2_tomans / 1000000.0, 2)
        elif total_price_mtomans is not None and area_m2:
            price_per_m2_mtomans = round(total_price_mtomans / area_m2, 2)
            
        post_url = f"https://divar.ir/v/{token}"
        
        return {
            "token": token,
            "title": title,
            "district": district,
            "city": city_name,
            "category": category_slug,
            "area_m2": area_m2,
            "rooms": rooms,
            "floor": floor,
            "total_floors": total_floors,
            "age": age,
            "total_price_tomans": total_price_tomans,
            "total_price_mtomans": total_price_mtomans,
            "price_per_m2_mtomans": price_per_m2_mtomans,
            "elevator": elevator,
            "parking": parking,
            "storage": storage,
            "authentic_photos": authentic_photos,
            "post_date": post_date_fallback,
            "url": post_url
        }
    except Exception:
        return None

def scrape_divar(filters, progress_callback=None):
    """
    Modular scraping function.
    filters: dict with target parameters
    progress_callback: function(status, message, current, total, matches) to report progress
    """
    def log(msg, status="running", current=0, total=0, matches=0):
        try:
            print(msg)
        except UnicodeEncodeError:
            try:
                enc = sys.stdout.encoding or 'utf-8'
                print(msg.encode(enc, errors='replace').decode(enc))
            except Exception:
                pass
        if progress_callback:
            progress_callback(status, msg, current, total, matches)

    log("Initializing Divar Real Estate Scraper...", status="running")
    
    # Resolve filters
    city_ids = filters.get("city_ids", ["1"])
    category = filters.get("category", "apartment-sell")
    
    # Map buy-commercial-property to commercial-sell for Divar API search compatibility
    api_category = category
    if category == "buy-commercial-property":
        api_category = "commercial-sell"
        
    area_min = filters.get("area_min", 40)
    area_max = filters.get("area_max", 140)
    
    # Price filters
    price_m2_min = filters.get("price_m2_min", 175.0)
    price_m2_max = filters.get("price_m2_max", 325.0)
    
    # Built year range
    year_min = filters.get("year_min", 0)
    year_max = filters.get("year_max", 9999)
    
    # Bedrooms filter
    rooms_req = filters.get("rooms", "Any")
    
    # Amenity constraints: Yes, No, Any
    elevator_req = filters.get("elevator", "Yes")
    parking_req = filters.get("parking", "Any")
    storage_req = filters.get("storage", "Any")
    
    # Authentic photos filter
    authentic_photos_req = filters.get("authentic_photos", "Any")
    
    districts_req = filters.get("districts", [])
    district_ids_req = filters.get("district_ids", [])
    
    price_total_min = filters.get("price_total_min", 0.0)
    price_total_max = filters.get("price_total_max", 9999.0)
    
    max_pages = filters.get("max_pages", 5)
    output_file = filters.get("output_file", "apartments.csv")
    
    # Set up city fallbacks based on city codes
    city_name_map = {
        "1": "تهران",
        "890": "تهران",
        "17": "اردبیل",
        "4": "اصفهان"
    }
    city_fallbacks = [city_name_map.get(cid, "تهران") for cid in city_ids]
    primary_city_fallback = city_fallbacks[0] if city_fallbacks else "تهران"
    
    session = requests.Session()
    
    # Load existing tokens from target file to enable incremental scraping
    existing_tokens = set()
    existing_records = []
    if os.path.exists(output_file):
        try:
            import pandas as pd
            df_existing = pd.read_csv(output_file, encoding="utf-8")
            if not df_existing.empty and "token" in df_existing.columns:
                existing_tokens = set(df_existing["token"].dropna().astype(str).tolist())
                existing_records = df_existing.to_dict(orient="records")
                log(f"Loaded {len(existing_tokens)} existing properties from {output_file} for incremental scraping.")
        except Exception as e:
            log(f"Could not load existing CSV {output_file} ({e}). Performing clean scrape.")
            
    # Prepare API Search Payload
    form_data_data = {
        "category": {"str": {"value": api_category}}
    }
    
    # 1. Size range
    if area_min or area_max:
        form_data_data["size"] = {
            "number_range": {
                "minimum": int(area_min) if area_min else 0,
                "maximum": int(area_max) if area_max else 999999
            }
        }
        
    # 2. Total Price range (in Tomans)
    # price_total_min is in Billion Tomans (e.g. 2.5 B = 2,500,000,000 Tomans)
    p_min = int(price_total_min * 1000000000) if price_total_min else 0
    p_max = int(price_total_max * 1000000000) if price_total_max else 999999999999
    
    # Only send price constraint to search payload if meaningful limits are active
    if price_total_min > 0 or price_total_max < 9999.0:
        form_data_data["price"] = {
            "number_range": {
                "minimum": p_min,
                "maximum": p_max
            }
        }
        
    # 3. Built year range
    # Only add to search payload if meaningful limits are specified (not broad defaults like 0-9999)
    if (year_min and year_min > 0) or (year_max and year_max < 9999):
        form_data_data["built_year"] = {
            "number_range": {
                "minimum": int(year_min) if year_min else 0,
                "maximum": int(year_max) if year_max else 9999
            }
        }
        
    # 4. Amenities (Elevator, Parking, Storage)
    if elevator_req == "Yes":
        form_data_data["has-elevator"] = {"bool": {"value": True}}
    elif elevator_req == "No":
        form_data_data["has-elevator"] = {"bool": {"value": False}}
        
    # Standardize parking/storage if possible in request
    if parking_req == "Yes":
        form_data_data["has-parking"] = {"bool": {"value": True}}
    elif parking_req == "No":
        form_data_data["has-parking"] = {"bool": {"value": False}}
        
    if storage_req == "Yes":
        form_data_data["has-storage"] = {"bool": {"value": True}}
    elif storage_req == "No":
        form_data_data["has-storage"] = {"bool": {"value": False}}

    if district_ids_req and "All" not in district_ids_req and len(district_ids_req) > 0:
        form_data_data["districts"] = {
            "repeated_string": {
                "value": [str(d_id) for d_id in district_ids_req]
            }
        }

    payload = {
      "city_ids": city_ids,
      "source_view": "CATEGORY_BREAD_CRUMB",
      "disable_recommendation": False,
      "map_state": {"camera_info": {"bbox": {}}},
      "search_data": {
        "form_data": {
          "data": form_data_data
        },
        "server_payload": {
          "@type": "type.googleapis.com/widgets.SearchData.ServerPayload",
          "additional_form_data": {
            "data": {
              "sort": {"str": {"value": "sort_date"}}
            }
          }
        }
      },
      "previous_place_ids": []
    }
    
    scraped_data = []
    seen_tokens = set()
    
    page = 1
    has_next = True
    total_processed_posts = 0
    total_matching_posts = 0
    
    while has_next and page <= max_pages:
        log(f"Page {page}/{max_pages}: Fetching listings from Divar...", status="running", current=page, total=max_pages, matches=total_matching_posts)
        try:
            r = session.post(
                "https://api.divar.ir/v8/postlist/w/search",
                headers=HEADERS,
                cookies=COOKIES,
                json=payload,
                timeout=15
            )
            
            if r.status_code != 200:
                log(f"Error: Failed to fetch search results from Divar. Status code: {r.status_code}", status="error")
                break
                
            resp_data = r.json()
            widgets = resp_data.get("list_widgets", [])
            
            post_widgets = [w for w in widgets if w.get("widget_type") == "POST_ROW"]
            log(f"Page {page}/{max_pages}: Found {len(post_widgets)} apartments. Crawling details...", status="running", current=page, total=max_pages, matches=total_matching_posts)
            
            # Extract pagination details
            pagination = resp_data.get("pagination", {})
            has_next = pagination.get("has_next_page", False)
            pagination_data = pagination.get("data", {})
            
            # Update payload for the next page
            if pagination_data:
                payload["pagination_data"] = pagination_data
            else:
                has_next = False
                
            # Process widgets
            for idx, w in enumerate(post_widgets):
                w_data = w.get("data", {})
                token = w_data.get("token")
                if not token or token in seen_tokens:
                    continue
                    
                # Skip if already in database
                if token in existing_tokens:
                    log(f"  -> [{idx+1}/{len(post_widgets)}] Listing {token} already in database. Skipping.")
                    continue
                    
                seen_tokens.add(token)
                
                # District and title from widget as fallback
                action_payload = w_data.get("action", {}).get("payload", {})
                web_info = action_payload.get("web_info", {})
                widget_district = web_info.get("district_persian", "")
                widget_title = w_data.get("title", "")
                
                # Fetch post date from widget action log
                action_log = w.get("action_log", {})
                server_side_info = action_log.get("server_side_info", {})
                info = server_side_info.get("info", {})
                sort_date = info.get("sort_date", "")
                
                # Log detail fetch
                total_processed_posts += 1
                detail_title_clean = fa_to_en_digits(widget_title)[:25]
                log(f"  -> [{idx+1}/{len(post_widgets)}] Fetching {token} ({detail_title_clean}...)...", 
                    status="running", current=page, total=max_pages, matches=total_matching_posts)
                
                # Fetch details
                detail = fetch_post_details(
                    session, 
                    token, 
                    post_date_fallback=sort_date,
                    city_fallback=primary_city_fallback,
                    category_fallback=category
                )
                
                # Polite scraping sleep
                time.sleep(random.uniform(0.6, 1.2))
                
                if not detail:
                    continue
                
                # Use fallbacks if detail values are empty
                if not detail["district"] and widget_district:
                    detail["district"] = fa_to_en_digits(widget_district)
                if not detail["title"] and widget_title:
                    detail["title"] = fa_to_en_digits(widget_title)
                    
                # Apply Filters:
                # 1. Area Range
                area = detail["area_m2"]
                if area is None or area < area_min or area > area_max:
                    continue
                    
                # 2. Built Year (via Age) Range
                age = detail["age"]
                year = (1405 - age) if age is not None else None
                if year is not None:
                    if year < year_min or year > year_max:
                        continue
                elif year_min > 0 or year_max < 9999:
                    continue
                    
                # 3. Bedrooms Constraint
                rooms = detail["rooms"]
                if rooms_req != "Any":
                    if rooms_req == "4+":
                        if rooms is None or rooms < 4:
                            continue
                    else:
                        try:
                            req_val = int(rooms_req)
                            if rooms != req_val:
                                continue
                        except ValueError:
                            pass
                    
                # 4. Amenity Requirements (Yes / No / Any)
                if elevator_req != "Any" and detail["elevator"] != elevator_req:
                    continue
                if parking_req != "Any" and detail["parking"] != parking_req:
                    continue
                if storage_req != "Any" and detail["storage"] != storage_req:
                    continue
                    
                # 5. Price per m²: target range
                price_per_m2 = detail["price_per_m2_mtomans"]
                if price_per_m2 is None or price_per_m2 < price_m2_min or price_per_m2 > price_m2_max:
                    continue
                    
                # 5.2 Total Price local constraint
                total_price_m = detail.get("total_price_mtomans")
                if total_price_m is not None:
                    total_price_b = total_price_m / 1000.0
                    if total_price_b < price_total_min or total_price_b > price_total_max:
                        continue
                elif price_total_min > 0:
                    continue
                    
                # 6. Authentic Photos Constraint
                auth_photos = detail.get("authentic_photos", "N/A")
                if authentic_photos_req != "Any" and auth_photos != authentic_photos_req:
                    continue
                    
                # 7. Districts Constraint
                dist_name = detail.get("district", "")
                if districts_req and "All" not in districts_req and len(districts_req) > 0:
                    match_found = False
                    norm_dist_name = normalize_farsi_string(dist_name)
                    for req_dist in districts_req:
                        if normalize_farsi_string(req_dist) == norm_dist_name:
                            match_found = True
                            break
                    if not match_found:
                        continue
                    
                # All filters passed! Add to scraped list
                scraped_data.append(detail)
                total_matching_posts += 1
                log(f"     [MATCH] Area: {area} m², Price/m²: {price_per_m2:.1f}M, Elevator: {detail['elevator']}.", 
                    status="running", current=page, total=max_pages, matches=total_matching_posts)
                
            page += 1
            
        except Exception as e:
            log(f"Error in main loop: {e}", status="error")
            break
            
    # Write to CSV
    columns = [
        "token", "title", "district", "city", "category", "area_m2", "rooms", "floor", "total_floors", "age",
        "total_price_tomans", "total_price_mtomans", "price_per_m2_mtomans", "elevator", "parking", "storage",
        "authentic_photos", "post_date", "url"
    ]
    
    # Merge newly scraped data with existing records (avoiding duplicates)
    newly_scraped_tokens = seen_tokens
    merged_data = list(scraped_data)
    for record in existing_records:
        rec_token = str(record.get("token", ""))
        if rec_token and rec_token not in newly_scraped_tokens:
            merged_data.append(record)
            
    log(f"Crawl finished. Found {len(scraped_data)} new listings across {page-1} pages. Database has total {len(merged_data)} unique records.", status="running")
    
    # Save using pandas if possible, otherwise standard CSV
    try:
        import pandas as pd
        df = pd.DataFrame(merged_data)
        if not df.empty:
            df = df[columns]
            df.to_csv(output_file, index=False, encoding="utf-8")
        else:
            pd.DataFrame(columns=columns).to_csv(output_file, index=False, encoding="utf-8")
        log(f"Saved database to {output_file} using Pandas.", status="completed", current=max_pages, total=max_pages, matches=total_matching_posts)
    except Exception as e:
        log(f"Pandas write failed ({e}). Falling back to csv module.", status="running")
        try:
            with open(output_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in merged_data:
                    clean_row = {col: row.get(col, "") for col in columns}
                    writer.writerow(clean_row)
            log(f"Saved database to {output_file} using csv module.", status="completed", current=max_pages, total=max_pages, matches=total_matching_posts)
        except Exception as ex:
            log(f"Failed to write CSV file: {ex}", status="error")
            return []
            
    return scraped_data

def main():
    print("====================================================")
    print("Divar.ir Real Estate Scraper — Tehran Apartments")
    print("====================================================")
    
    max_pages = 10
    if len(sys.argv) > 1:
        try:
            max_pages = int(sys.argv[1])
        except ValueError:
            pass
            
    filters = {
        "city_ids": ["1"],
        "category": "apartment-sell",
        "area_min": 40,
        "area_max": 140,
        "price_m2_min": 175.0,  # 250M - 30%
        "price_m2_max": 325.0,  # 250M + 30%
        "elevator": "Yes",
        "parking": "Any",
        "storage": "Any",
        "max_pages": max_pages,
        "output_file": "apartments.csv"
    }
    
    scrape_divar(filters)
    print("====================================================")

if __name__ == "__main__":
    main()
