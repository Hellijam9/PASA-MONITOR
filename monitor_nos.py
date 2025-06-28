def load_neo_mapping():
    today = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    mapping = {}

    for state_code, url_template in NEO_CSV_LINKS.items():
        url = url_template.format(today=today)
        try:
            df = pd.read_csv(url, header=None)  # Don't skip any rows

            for _, row in df.iterrows():
                if len(row) < 12:
                    continue  # Not enough columns
                if pd.isna(row[2]):
                    continue  # No outage ID

                outage_id = str(row[2]).strip().lstrip("0")
                if outage_id == "" or outage_id.lower() == "nan":
                    continue

                mapping[outage_id] = {
                    "state": str(row[3]).strip() if pd.notna(row[3]) else state_code,
                    "owner": str(row[4]).strip() if pd.notna(row[4]) else "?",
                    "substation_desc": str(row[6]).strip() if pd.notna(row[6]) else "?",
                    "equipment_desc": str(row[9]).strip() if pd.notna(row[9]) else "?",
                    "set_desc": str(row[11]).strip() if pd.notna(row[11]) else "?"
                }

        except Exception as e:
            print(f"⚠️ Failed loading NeoPoint CSV for {state_code}: {e}")

    print(f"📦 NeoPoint mapping loaded with {len(mapping)} outage IDs")
    return mapping
