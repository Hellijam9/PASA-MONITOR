if __name__ == "__main__":
    # TEMP: Compare two known URLs directly
    url1 = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241500_0000000469074180.zip"
    url2 = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/PUBLIC_MTPASADUIDAVAILABILITY_202506241800_0000000469093579.zip"

    log(f"Manually comparing:\n- {url1.split('/')[-1]}\n- {url2.split('/')[-1]}")

    df1 = extract_csv_from_zip(url1)
    df2 = extract_csv_from_zip(url2)
    changes = compare_availability(df1, df2)

    if changes.empty:
        log("No changes detected.")
    else:
        summary = format_summary(changes)
        print("\n" + summary)
        send_ntfy(summary)
        log("Alert sent.")
