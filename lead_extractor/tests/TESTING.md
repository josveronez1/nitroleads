# Testes do lead_extractor

## Rodar todos os testes

```bash
python manage.py test lead_extractor
```

Com banco de teste reutilizado (evita erro "database is being accessed by other users"):

```bash
python manage.py test lead_extractor --keepdb
```

## Projeto clone e banco de dados

Se este repositório for um **clone** do projeto original e os testes insistirem em usar o mesmo banco do projeto original:

1. **Causa:** O Django usa `DATABASE_URL` do arquivo `.env`. Se o clone tiver o mesmo `.env` (ou nenhum), o mesmo PostgreSQL será usado e o banco de teste terá o mesmo nome (`test_<nome_do_banco>`), podendo conflitar com o outro projeto.

2. **Solução:** No **clone**, use um banco dedicado para desenvolvimento/testes:
   - Crie um banco no PostgreSQL (ex: `nitroleads_clone` ou `nitroleads_test`).
   - No `.env` do clone, defina:
     ```env
     DATABASE_URL=postgres://usuario:senha@localhost:5432/nitroleads_clone
     ```
   - Assim o banco de teste será `test_nitroleads_clone`, separado do projeto original.

3. **Alternativa para testes rápidos:** Usar SQLite só nos testes criando um `settings_test.py` que sobrescreve `DATABASES` com SQLite e rodar:
   ```bash
   python manage.py test lead_extractor --settings=lead_extraction.settings_test
   ```
   (requer configurar esse módulo de settings no projeto.)

## Estrutura dos testes

| Arquivo | O que testa |
|---------|-------------|
| `test_viper_queue.py` | Fila Viper: enqueue, process_next_request, mark_request_completed/failed |
| `test_normalization.py` | normalize_niche, normalize_location, remove_accents |
| `test_lead_sanitizer.py` | sanitize_lead_data (ocultar QSA/telefones) |
| `test_serper_service.py` | _normalize_company_name_for_cache, normalize_places_response (sem HTTP) |
| `test_viper_api.py` | sanitize_socios_for_storage, _normalize_cpf_api_response (sem HTTP) |
| `test_cache_service.py` | get_or_create_normalized_niche, get_cached_search, create_cached_search, get_cnpjs_from_user_last_3_searches, cleanup_old_search_accesses |
| `test_security.py` | (existente) |

Testes que chamam APIs externas (Serper, Viper HTTP) não estão incluídos; use mocks ou testes de integração manuais se precisar.
