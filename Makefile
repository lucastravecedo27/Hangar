# Atajos de Hangar.  `make` sin nada muestra la ayuda.
# En el servidor se usa ./desplegar.sh (ver DESPLIEGUE.md).
LOCAL = docker compose -f docker-compose.local.yml
SERVIDOR ?=

.DEFAULT_GOAL := ayuda
.PHONY: ayuda local parar logs shell pruebas produccion-local limpiar desplegar

ayuda:
	@echo "make local              levanta Hangar en http://localhost:8000 (código en vivo)"
	@echo "make parar              apaga lo local (los datos se conservan)"
	@echo "make logs               logs de la app local"
	@echo "make shell              terminal dentro del contenedor local"
	@echo "make pruebas            corre pytest dentro de Docker contra PostgreSQL"
	@echo "make produccion-local   prueba el stack de PRODUCCIÓN completo en https://localhost"
	@echo "make desplegar SERVIDOR=root@IP   publica en el VPS"

local:
	$(LOCAL) up -d --build
	@echo "→ http://localhost:8000"

parar:
	$(LOCAL) down
	-docker compose -p hangar-prod-local --env-file servidor/env.produccion-local down

logs:
	$(LOCAL) logs -f app

shell:
	$(LOCAL) exec app bash

pruebas:
	$(LOCAL) up -d --wait db
	-$(LOCAL) exec -T db psql -U postgres -c "CREATE DATABASE hangar_pruebas OWNER hangar" 2>/dev/null
	$(LOCAL) run --rm --build -T -u root --entrypoint sh \
	  -e DATABASE_URL=postgresql://hangar:hangar@db:5432/hangar_pruebas app \
	  -c "pip install -q pytest -c constraints.txt && python manage.py init >/dev/null && \
	      (python manage.py empresas | grep -q . || python manage.py crear-empresa Pruebas) && \
	      python -m pytest pruebas -q -p no:cacheprovider"

# El mismo docker-compose.yml del servidor (Caddy + respaldos + tareas) en tu Mac, con
# certificado local. Sirve para probar el despliegue antes de subirlo.
produccion-local:
	docker compose -p hangar-prod-local --env-file servidor/env.produccion-local up -d --build
	@echo "→ https://localhost  (el navegador avisará del certificado local: es normal)"

desplegar:
	@test -n "$(SERVIDOR)" || (echo "uso: make desplegar SERVIDOR=root@IP" && exit 1)
	./desplegar.sh $(SERVIDOR)
