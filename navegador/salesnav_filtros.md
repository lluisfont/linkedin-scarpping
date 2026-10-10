# Construir URLs de búsqueda de Sales Navigator

La forma **más fiable** es que el usuario monte la búsqueda en Sales Navigator y pegue la URL.
Si no la da, se construye así:

```
https://www.linkedin.com/sales/search/people?query=(filters:List(FILTRO1,FILTRO2,...))
```

Cada filtro:
```
(type:TIPO,values:List((id:ID,text:TEXTO,selectionType:INCLUDED),(...)))
```
- Codificar espacios como `%20`, comas dentro de un texto como `%2C`, `+` como `%2B`.
- Varios valores dentro de un mismo filtro se combinan con **O**; filtros distintos, con **Y**.
- Para paginar, añadir `&page=N` (25 resultados por página, máximo 100 páginas = 2.500).

## Filtros con códigos fijos

### COMPANY_HEADCOUNT (empleados de la empresa actual)
| id | texto |
|---|---|
| B | 1-10 |
| C | 11-50 |
| D | 51-200 |
| E | 201-500 |
| F | 501-1000 |
| G | 1001-5000 |
| H | 5001-10000 |
| I | 10001%2B |

"Más de 1000 empleados" = G + H + I.

### FUNCTION (función) — comprobar la primera vez contra la interfaz
| id | función |
|---|---|
| 12 | Human Resources |
| 25 | Sales |
| 15 | Marketing |
| 10 | Finance |
| 13 | Information Technology |
| 18 | Operations |
| 14 | Legal |
| 8 | Engineering |

### SENIORITY_LEVEL — comprobar la primera vez contra la interfaz
| id | nivel |
|---|---|
| 220 | Director |
| 300 | Vice President |
| 310 | CXO |
| 320 | Owner / Partner |
| 210 | Experienced Manager |
| 200 | Entry Level Manager |

## Filtros de texto libre (sin id)

### CURRENT_TITLE (cargo actual)
```
(type:CURRENT_TITLE,values:List((text:Director%20de%20Recursos%20Humanos,selectionType:INCLUDED),(text:HR%20Director,selectionType:INCLUDED)))
```
Meter variantes de idioma y género: "Director/Directora de Recursos Humanos", "Director/a de RRHH",
"HR Director", "Head of HR", "Head of People", "People Director", "CHRO", "Chief People Officer".

## Filtros con id que hay que averiguar: REGION (geografía)

Los ids de zona (`geoUrn`) no son deducibles. Mirar primero en `config/geo_ids.json`.
Si no está:
1. Abrir `https://www.linkedin.com/sales/search/people`, abrir el filtro **Geography / Región**,
   escribir la zona (p. ej. "Barcelona") y elegir la sugerencia correcta.
2. Leer la URL resultante (`location.href`) y sacar el `(id:NNN,text:...)` del filtro `REGION`.
3. Guardarlo en `config/geo_ids.json` para la próxima vez.

## Ejemplo: "Director de RRHH en Barcelona, empresa de más de 1000 empleados"
```
https://www.linkedin.com/sales/search/people?query=(filters:List((type:CURRENT_TITLE,values:List((text:Director%20de%20Recursos%20Humanos,selectionType:INCLUDED),(text:Directora%20de%20Recursos%20Humanos,selectionType:INCLUDED),(text:HR%20Director,selectionType:INCLUDED),(text:Head%20of%20HR,selectionType:INCLUDED),(text:Director%20de%20RRHH,selectionType:INCLUDED))),(type:COMPANY_HEADCOUNT,values:List((id:G,text:1001-5000,selectionType:INCLUDED),(id:H,text:5001-10000,selectionType:INCLUDED),(id:I,text:10001%2B,selectionType:INCLUDED))),(type:REGION,values:List((id:<ID_BARCELONA>,text:Barcelona,selectionType:INCLUDED)))))
```
Después de navegar, comprobar en la página que los filtros aplicados son los esperados
(chips de filtros visibles) antes de extraer.
