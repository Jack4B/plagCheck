# AGENTS.md

## Rola agentów w projekcie Plagiarism Detector (CT8)

### Główne zasady

- Każdy agent pracuje na jednym etapie naraz.
- Po zakończeniu etapu: aktualizacja CLAUDE.md + commit.
- Dokumenty użytkowników nigdy nie są trwale przechowywane bez wyraźnej zgody.
- Wszystkie zmiany przechodzą przez code review.
- Uwzględniaj ograniczenia CT8 (zasoby, sposób uruchamiania procesów).
- **Nie próbuj** integrować z ORPPD — API jest tylko do depozytu przez uczelnie.

### Agenci i odpowiedzialności

| Agent | Odpowiedzialność | Kiedy używać |
|-------|------------------|--------------|
| **Planner** | Konspekt, plan techniczny, kryteria akceptacji, ocena limitów CT8 | Start projektu / nowa funkcja |
| **Designer** | UX, ekrany (upload, postęp, raport), design system | Przed implementacją UI |
| **Backend** | FastAPI, NLP, similarity, wyszukiwanie, raport (lekkie rozwiązania) | Implementacja logiki |
| **Frontend** | Interfejs, podświetlanie fragmentów, historia | Implementacja UI |
| **Tester** | Testy jednostkowe, integracyjne, E2E | Po implementacji modułu |
| **Reviewer** | Code review, bezpieczeństwo, prostota, RODO, limity CT8 | Przed mergem |
| **Deployer** | Deployment na CT8 (Passenger/screen, MySQL, cron) | Wdrożenie |

### Workflow

1. Planner → plan + CLAUDE.md update (uwzględnij CT8)
2. Designer → makiety / opis ekranów
3. Backend + Frontend (równolegle gdzie możliwe)
4. Tester → testy
5. Reviewer → przegląd
6. Deployer → wdrożenie na CT8
7. Na końcu: aktualizacja pamięci (`docs/solutions/`, `docs/CONCEPTS.md`)

### Definition of Done

- Kod z testami
- Zaktualizowany CLAUDE.md
- Brak trwałych plików użytkowników
- Disclaimer widoczny w UI
- Raport działa (procent + podświetlenia + linki)
- Działa na CT8 (lub ma jasny plan obejścia limitów)

### Ryzyka do pilnowania

- Limity API wyszukiwarek
- Fałszywe pozytywy (cytaty, definicje)
- RODO / prywatność
- Jakość modeli dla języka polskiego
- **Limity CT8** (RAM, procesy, brak pełnego ASGI)
- **ORPPD** — brak publicznego dostępu do treści prac

---
*Dokument dla agentów pracujących nad aplikacją do wstępnego wykrywania plagiatu na CT8.*
