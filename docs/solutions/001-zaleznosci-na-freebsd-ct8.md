# 001 — Zależności instalowalne na CT8 (FreeBSD) bez kompilacji

**Problem.** CT8 to FreeBSD — PyPI nie ma tam kół binarnych. `pydantic` v2 (pydantic-core, Rust),
`lxml`, `PyMuPDF`, `numpy`/`scikit-learn`, `torch`, `faiss` wymagają kompilacji albo w ogóle nie
działają; kompilacja przy ~512 MB RAM jest zawodna.

**Rozwiązanie.**
- FastAPI 0.115 + **pydantic v1** (`pydantic-1.10.x-py3-none-any.whl`) — kod nie używa modeli
  pydantic (słowniki + `Form`/`File`), więc działa też na v2 (testy na obu).
- DOCX/ODT: `zipfile` + `xml.etree` zamiast `python-docx`/`lxml`; PDF: `pypdf` zamiast PyMuPDF.
- HTTP: `urllib` zamiast `httpx`/`requests`.
- SQLAlchemy instalowane z `--no-deps`: na FreeBSD `platform_machine == "amd64"` dociąga
  `greenlet` (C++), potrzebny tylko dla asyncio — pomijamy go.
- `scripts/build_package.sh` pobiera koła z `--platform any --abi none` — **build się wywali**,
  jeśli jakakolwiek zależność nie jest czystym Pythonem. To automatyczna kontrola.

**Weryfikacja.** Instalacja z paczki do czystego venv (`pydantic.compiled == False`) + E2E przez
serwer WSGI — przechodzi.
