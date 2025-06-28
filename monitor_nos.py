def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url); r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        fn = z.namelist()[0]
        print(f"✅ Extracting: {fn}")
        lines = [line.decode('utf-8','ignore')
                 for line in z.open(fn)
                 if line.startswith(b'D')]

    cols = [
      "RECTYPE","REPORTID","RECORDTYPE","VERSION",
      "OUTAGEID","SUBSTATIONID","EQUIPMENTTYPE","EQUIPMENTID",
      "STARTTIME","ENDTIME","SUBMITTEDDATE",
      "OUTAGESTATUSCODE","RESUBMITREASON","RESUBMITOUTAGEID",
      "RECALLTIMEDAY","RECALLTIMENIGHT",
      "REASON","ISSECONDARY","ACTUAL_STARTTIME",
      "ACTUAL_ENDTIME","COMPANYREFCODE","ELEMENTID"
    ][:len(lines[0].split(','))]

    df = pd.read_csv(
        StringIO(''.join(lines)),
        names=cols, header=None,
        quotechar='"', skipinitialspace=True
    )

    # ←— filter out the constraint-set header & rows
    df = df[df["RECORDTYPE"] == "OUTAGEDETAIL"].copy()

    # parse your m/d/yyyy H:MM timestamps
    for dt_col in ("STARTTIME","ENDTIME","ACTUAL_STARTTIME","ACTUAL_ENDTIME"):
        df[dt_col] = pd.to_datetime(
            df[dt_col].astype(str)
                     .str.replace('"','')
                     .str.strip(),
            format="%m/%d/%Y %H:%M",
            errors="coerce"
        )

    return df
