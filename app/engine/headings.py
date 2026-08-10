"""Decide whether a file's first row names the columns or is the first record.

This is the most dangerous guess the tool makes. A heading row is not data,
so nothing in it is ever replaced — mistake somebody's record for the
headings and their name and SSN ship inside a file labelled "redacted",
with no warning, because the leak check only ever looks at rows.

It has been wrong five separate ways, each time in a value shape nobody
had enumerated: a 4-digit id, money, a parenthesised phone number, a
text-month date, a short code. Enumerating shapes was the wrong approach,
so the order of evidence is now:

1. A word that names a column ("Name", "Total") settles it. That is what a
   reader actually goes on, and no shape comparison can see it.
2. A shape that is never a column name (an address, a phone number, a
   date) settles it the other way.
3. Otherwise the row is compared to the columns beneath it: a row built
   like its data is a record, whatever format it happens to use.
4. With no evidence at all, assume a record — see `has_header`.
"""

import re
import unicodedata

from app.engine.values import parse_date


def _fold(text: str) -> str:
    """Lowercase and strip accents, so 'Prénom' matches 'prenom' and
    'Teléfono' matches 'telefono'. Accented spellings are the norm in the
    languages this list covers, so matching without them would be close to
    useless."""
    stripped = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in stripped if not unicodedata.combining(c))

# Any script's letters, not just A-Z: a Cyrillic or CJK column otherwise
# compares as punctuation and its first record gets read as a heading.
_LETTER_RUN = re.compile(r"[^\W\d_]+", re.UNICODE)
_DIGIT_RUN = re.compile(r"\d+")
_NUMERIC_CLASS = re.compile(r"^[^A-Za-z]*\d[\d\s,.$€£¥%()+-]*$")

# Shapes no one names a column after. One is enough to say the row is a
# record, and no comparison can argue with it.
_UNAMBIGUOUS_SHAPES = (
    re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),  # ada@school.edu
    # 111-22-3333 and (555) 555-1000. The leading "(" matters: the pattern
    # used to anchor on a digit, so the parenthesised form — the one this
    # tool's own fake-phone generator emits — was never recognised.
    re.compile(r"^\+?[\d(][\d\s().-]{6,}$"),
    re.compile(r"^\d{5,}$"),                         # long id run
    re.compile(r"^\d{4}-\d{2}-\d{2}"),               # 2024-03-12
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),        # 3/12/2024
)

# Values that mean "nothing here" — neither a heading nor a record, so they
# vote neither way. One "N/A" in the first row used to outvote four columns
# of matching record ids.
_NO_VOTE = {
    "", "-", "--", "n/a", "na", "null", "none", "nan", "pending", "tbd",
    "unknown", "withheld", "redacted", "exempt", "n.a.", "not collected",
}

# Words that name a column and are almost never somebody's data. Seeing
# "Name" tells a reader the row labels the columns however the other cells
# look, and that is the single strongest signal available.
#
# Kept deliberately short and concrete. A word earns its place only if it
# would be odd as a cell value: "Name" yes, "Active" no — plenty of status
# columns contain it.
_HEADING_WORDS = {
    # english
    "name", "names", "id", "ids", "identifier", "code", "codes", "number",
    "no", "num", "date", "dates", "time", "year", "month", "day", "email",
    "mail", "phone", "tel", "mobile", "cell", "fax", "address", "street",
    "city", "town", "state", "province", "county", "country", "region",
    "zip", "zipcode", "postcode", "amount", "total", "subtotal", "count",
    "sum", "score", "grade", "rank", "rate", "price", "cost", "value",
    "notes", "note", "comment", "comments", "description", "desc", "title",
    "type", "category", "status", "gender", "sex", "age", "dob", "ssn",
    "first", "last", "middle", "surname", "initials", "salary", "wage",
    "department", "dept", "division", "unit", "school", "district",
    "student", "patient", "client", "employee", "staff", "member", "row",
    "item", "product", "quantity", "qty", "term", "semester", "program",
    "course", "section", "teacher", "provider", "diagnosis",
    "contact", "guardian", "parent", "kin",
    # spanish / portuguese
    "nombre", "nombres", "apellido", "apellidos", "correo", "telefono",
    "direccion", "ciudad", "estado", "pais", "fecha", "edad", "sexo",
    "codigo", "numero", "cantidad", "importe", "total", "descripcion",
    "nome", "sobrenome", "endereco", "cidade", "pais", "data", "idade",
    "telefone", "cadastro", "valor", "quantidade",
    # french
    "nom", "prenom", "adresse", "ville", "pays", "courriel", "telephone",
    "date", "age", "montant", "quantite", "numero", "libelle", "statut",
    # german
    "name", "vorname", "nachname", "adresse", "strasse", "stadt", "land",
    "datum", "alter", "betrag", "anzahl", "nummer", "bezeichnung", "status",
}

# Words that can stand beside a heading word without changing what the cell
# is: "Emergency Contact Name", "Date of Birth".
_HEADING_QUALIFIERS = {
    "of", "the", "and", "or", "per", "by", "at", "in", "on", "for",
    "de", "del", "la", "el", "du", "des", "von", "der", "die", "das",
    "emergency", "primary", "secondary", "home", "work", "mailing",
    "billing", "current", "previous", "former", "full", "short", "legal",
    "preferred", "birth", "start", "end", "due", "paid", "billed", "net",
    "gross", "next", "line",
    "nacimiento", "naissance", "geburt", "nascimento",  # "of birth"
}

MAX_LABEL_WORDS = 4
MAX_LABEL_LENGTH = 40
SAMPLE_ROWS = 20


def names_a_column(cell: str) -> bool:
    """Whether this cell reads as a label rather than a value.

    The whole cell has to be made of labelling words: 'Client Name' does,
    'ada@school.edu' does not, even though it contains 'school'. A label
    also carries no number — 'Grade' names a column, 'Grade 5' is
    somebody's grade.
    """
    text = cell.strip()
    if (
        not text
        or "@" in text
        or len(text) > MAX_LABEL_LENGTH
        or _DIGIT_RUN.search(text)
    ):
        return False
    tokens = [t for t in _LETTER_RUN.findall(_fold(text)) if t]
    if not tokens or len(tokens) > MAX_LABEL_WORDS:
        return False
    return bool(set(tokens) & _HEADING_WORDS) and set(tokens) <= (
        _HEADING_WORDS | _HEADING_QUALIFIERS
    )


def is_unambiguous_value(cell: str) -> bool:
    """A shape that is never a column name in any file."""
    text = cell.strip()
    if not text:
        return False
    return bool(
        any(shape.match(text) for shape in _UNAMBIGUOUS_SHAPES) or parse_date(text)
    )


def skeleton(value: str) -> str:
    """A value's character-class pattern, digits kept at their own length.

    '(555) 555-1000' -> '(999) 999-9999', 'AB-100' -> 'a-999',
    'Mar 1, 2024' -> 'a 9, 9999'. Comparing skeletons says whether the first
    row is built like the rows beneath it without needing a rule per format.
    Digit length matters: '2023' over two-digit scores names a year column,
    while '2001' over 2002 and 2003 is a record's own id.
    """
    text = _LETTER_RUN.sub("a", value.strip())
    return _DIGIT_RUN.sub(lambda m: "9" * len(m.group()), text)


def _column_evidence(text: str, column: list[str]) -> int:
    """+1 if this column says the cell above it is a record, -1 if it says
    the cell is a heading, 0 if it cannot tell."""
    # A column of numbers is the clearest signal there is, and it holds even
    # when the numbers are different lengths — "7" belongs above 1234 as
    # surely as 1001 does.
    if all(_NUMERIC_CLASS.match(v) for v in column):
        return 1 if _NUMERIC_CLASS.match(text) else -1

    shapes = {skeleton(v) for v in column}
    if len(shapes) != 1:
        # A column whose own values disagree about their shape says nothing
        # about the row above it — and picking a "most common" shape made
        # the answer depend on the hash seed.
        return 0
    if skeleton(text) in shapes:
        return 1
    # A mismatch is not evidence of a heading. Text varies on its own —
    # "Mrs. Emma Smith MD" is shaped differently from "Amy Kane" and is
    # still a name. Only a column of numbers, or a word that names a
    # column, says the row above is a heading.
    return 0


def has_header(first_row: list[str], body: list[list[str]] | None = None) -> bool:
    """Whether `first_row` names the columns rather than being a record."""
    filled = [c.strip() for c in first_row if c.strip()]
    if not filled:
        return True
    if any(names_a_column(cell) for cell in filled):
        return True
    if not body:
        # One row on its own: a record if it says so, otherwise assume an
        # export that produced headings and no rows, which is far more
        # common and is rejected rather than processed.
        return not any(is_unambiguous_value(cell) for cell in filled)
    if any(is_unambiguous_value(cell) for cell in filled):
        return False

    heading_evidence = data_evidence = 0
    for index, cell in enumerate(first_row):
        text = cell.strip()
        if text.lower() in _NO_VOTE:
            continue
        column = [
            row[index].strip()
            for row in body[:SAMPLE_ROWS]
            if index < len(row) and row[index].strip().lower() not in _NO_VOTE
        ]
        if not column:
            continue
        vote = _column_evidence(text, column)
        if vote > 0:
            data_evidence += 1
        elif vote < 0:
            heading_evidence += 1

    if data_evidence and data_evidence >= heading_evidence:
        return False
    if heading_evidence:
        return True

    # No column could be compared and nothing in the row names a column.
    # Assume a record: mistaking a heading row for data costs the column
    # names and redacts a row of labels, while mistaking a record for a
    # heading puts a real person in a row redaction never touches.
    return False
