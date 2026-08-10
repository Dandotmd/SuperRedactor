"""Regressions from the fourth review round."""

import io

from openpyxl import Workbook

from app.engine.detect import suggest_type
from app.engine.leakcheck import find_leaks
from app.engine.readers import Sheet, read_file
from app.engine.redactor import redact
from app.engine.standardize import make_template


# ---- the check must describe the file you actually download ---------------

def test_the_warning_shown_matches_the_file_downloaded():
    """The check runs the redaction to see what happens. Without a shared
    seed it would be measuring a different random run than the download."""
    import io
    import zipfile

    from faker import Faker
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    faker = Faker()
    pool: set[str] = set()
    while len(pool) < 400:
        pool.add(faker.first_name())
    names = sorted(pool)

    csv = "Student First,Guardian First\n" + "\n".join(
        f"{names[i]},{names[i + 200]}" for i in range(200)
    )
    session = client.post(
        "/api/upload",
        files={"file": ("roster.csv", io.BytesIO(csv.encode()), "text/csv")},
    ).json()["session_id"]
    config = {
        "Sheet1": {"Student First": "first_name", "Guardian First": "first_name"}
    }

    checked = client.post(
        "/api/redact/check", json={"session_id": session, "config": config}
    ).json()
    resp = client.post("/api/redact", json={"session_id": session, "config": config})
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    out = zf.read([n for n in zf.namelist() if n.endswith(".csv")][0]).decode()
    produced = {c.strip() for line in out.splitlines()[1:] for c in line.split(",")}

    if produced & set(names):
        assert checked["weak_columns"], (
            f"{len(produced & set(names))} real names in the download, "
            f"with a clean check beforehand"
        )


# ---- N1: delimiter sniffing -----------------------------------------------

def test_pipe_delimited_file_whose_names_all_contain_a_comma():
    # "LAST, FIRST" gives every row the same comma count, which fooled the
    # sniffer into reading a 16-column file as 2 columns
    rows = [f"H0AK0010{i}|LAMB, THOMAS|NNE|2020|AK" for i in range(9)]
    data = ("\n".join(rows) + "\n").encode()
    sheets = read_file("cn.csv", data)
    assert len(sheets[0].headers) == 5
    assert len(sheets[0].rows) == 9
    assert sheets[0].rows[0][1] == "LAMB, THOMAS"


def test_plain_comma_file_is_still_comma_delimited():
    data = b"name,email\nAda,ada@x.org\nGrace,grace@x.org\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name", "email"]


# ---- N2: headerless xlsx --------------------------------------------------

def test_headerless_xlsx_is_detected():
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    for i in range(4):
        ws.append([f"H0AK0010{i}", "LAMB THOMAS", "AK", "111-22-3333"])
    buf = io.BytesIO()
    wb.save(buf)

    sheets = read_file("cn.xlsx", buf.getvalue())
    assert sheets[0].headers[0] == "column_1"
    assert len(sheets[0].rows) == 4


def test_xlsx_with_a_real_header_row_keeps_it():
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append(["Name", "Email", "Score"])
    ws.append(["Ada", "ada@x.org", 88])
    ws.append(["Grace", "grace@x.org", 91])
    buf = io.BytesIO()
    wb.save(buf)

    sheets = read_file("x.xlsx", buf.getvalue())
    assert sheets[0].headers == ["Name", "Email", "Score"]


# ---- N3: values ending in punctuation --------------------------------------

def test_a_name_ending_in_a_full_stop_is_found_in_a_sentence():
    sheets = [
        Sheet(
            name="S",
            headers=["Client", "Notes"],
            rows=[
                ["Ryan Hall Jr.", "spoke to Ryan Hall Jr. today"],
                ["Ada Lovelace", "spoke to Ada Lovelace today"],
                ["Bo Diddley", "nothing"],
            ],
        )
    ]
    leaks = find_leaks(sheets, {"S": {"Client": "person_name"}})
    assert leaks and leaks[0].count == 2, leaks


# ---- N4: removed columns as leak sources -----------------------------------

def test_a_value_from_a_removed_column_quoted_elsewhere_is_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Notes"],
            rows=[
                ["Ida Wells", "Ida Wells called"],
                ["Bo Diddley", "nothing"],
                ["Cy Young", "nothing"],
            ],
        )
    ]
    assert find_leaks(sheets, {"S": {"Student": "drop"}})


# ---- N5: case is data in identifier columns --------------------------------

def test_case_distinct_identifiers_stay_distinct():
    sheets = [
        Sheet(name="S", headers=["code"], rows=[["aB3xK9"], ["Ab3Xk9"], ["ZZ9zz1"]])
    ]
    out, mapping = redact(sheets, {"S": {"code": "format_preserving"}})
    produced = [r[0] for r in out[0].rows]
    assert produced[0] != produced[1], "two different IDs must not share a fake"
    assert len(mapping["S"]["code"]) == 3


def test_case_variants_of_a_name_still_share_a_fake():
    sheets = [
        Sheet(name="S", headers=["name"], rows=[["Ada Lovelace"], ["ADA LOVELACE"]])
    ]
    out, _ = redact(sheets, {"S": {"name": "person_name"}})
    assert out[0].rows[0][0] == out[0].rows[1][0]


# ---- N7: role words must not over-trigger ----------------------------------

def test_role_word_with_a_non_name_qualifier_is_not_a_name():
    for header in (
        "Employee Number", "Patient Number", "Client Code", "Staff Count",
        "Customer Segment", "Teacher Rating", "Student Count",
    ):
        assert suggest_type(header) != "person_name", header


def test_plain_role_words_are_still_names():
    for header in ("Patient", "Student", "Guardian", "Emergency Contact"):
        assert suggest_type(header) == "person_name", header


# ---- templates: remembering values is opt-in -------------------------------

def test_templates_do_not_remember_values_by_default():
    sheet = Sheet(
        name="S",
        headers=["Program", "Dx", "Rx", "ICD10"],
        rows=[
            ["Housing", "Asthma", "Albuterol", "J45"],
            ["Care", "Diabetes", "Metformin", "E11"],
            ["Housing", "Asthma", "Albuterol", "J45"],
            ["Care", "Diabetes", "Metformin", "E11"],
            ["Housing", "Asthma", "Albuterol", "J45"],
            ["Care", "Diabetes", "Metformin", "E11"],
        ],
    )
    template = make_template(sheet, name="t")
    for column in template["columns"]:
        assert "values" not in column, column["name"]
    # the columns that could remember a list are offered, not applied
    assert set(template["can_remember_values"]) >= {"Program", "Dx", "Rx", "ICD10"}
