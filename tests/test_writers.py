from app.engine.readers import Sheet, read_file
from app.engine.writers import write_csv, write_xlsx


def test_csv_round_trip():
    sheet = Sheet(name="Sheet1", headers=["name", "email"], rows=[["Sarah", "s@x.com"]])
    data = write_csv(sheet)
    back = read_file("out.csv", data)
    assert back[0].headers == ["name", "email"]
    assert back[0].rows == [["Sarah", "s@x.com"]]


def test_csv_quotes_values_with_commas():
    sheet = Sheet(name="Sheet1", headers=["address"], rows=[["1 Main St, Apt 2"]])
    back = read_file("out.csv", write_csv(sheet))
    assert back[0].rows == [["1 Main St, Apt 2"]]


def test_xlsx_round_trip_multiple_sheets():
    sheets = [
        Sheet(name="Students", headers=["id", "name"], rows=[["101", "Sarah"]]),
        Sheet(name="Sessions", headers=["sid"], rows=[["101"], ["102"]]),
    ]
    back = read_file("out.xlsx", write_xlsx(sheets))
    assert [s.name for s in back] == ["Students", "Sessions"]
    assert back[0].rows == [["101", "Sarah"]]
    assert back[1].rows == [["101"], ["102"]]
