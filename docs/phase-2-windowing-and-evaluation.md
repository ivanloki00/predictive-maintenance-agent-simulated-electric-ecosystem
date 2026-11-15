# Especificación v1: regímenes, ventanas y evaluación

## Alcance

Esta especificación define la lógica determinista que precede a la inferencia.
La familia del activo y su perfil se conocen por metadatos; no se infieren a
partir de la irradiancia. El detector de régimen, el buffer, la selección de
ventana y la evaluación no dependen de un LLM.

Los umbrales y duraciones se leen de una configuración versionada. Los valores
que dependen de resolución de sensores, activos o coste de mantenimiento quedan
pendientes de calibración; no se inventan como límites de seguridad.

## Clasificación de régimen

### Freesun / solar

- Regímenes: `solar_active`, `solar_low` y `unknown`.
- La señal primaria es `irradiance_w_m2`. La potencia DC puede servir como
  alternativa documentada si la irradiancia no está disponible; no se mezclan
  ambas señales sin especificar cuál gobierna la clasificación.
- Configurar dos umbrales, `U_solar_on > U_solar_off`, para histéresis.
  Confirmar el cambio solo después de que la señal permanezca más allá del
  umbral correspondiente durante `t_debounce_s`.
- Si la señal falta o no es válida, el régimen es `unknown`; no se interpreta
  una lectura ausente como ausencia de sol ni como modo NB. No se emite una
  predicción dependiente del régimen hasta recuperar contexto válido.

### Cargador NB

- Regímenes: `idle`, `charging_steady`, `charging_ramp` y `unknown`.
- Clasificar usando `ev_session_active` y `ev_power_kw`, no la irradiancia.
  La sesión activa inicia `charging`; distinguir `charging_ramp` cuando la
  variación de potencia supera el umbral configurable `U_ramp_kw_per_s`.
- Aplicar histéresis y debounce al ruido o al fin de sesión, sin esperar el
  debounce para reconocer una rampa de carga evidente. Si faltan las señales
  necesarias, devolver `unknown`.

Los regímenes describen el contexto de operación, no estados de salud ni
etiquetas de fallo. Una transición solar/noche no crea una nueva ejecución ni
borra la etiqueta de degradación acumulada.

## Ventanas temporales

La cadencia inicial `C` es 1 segundo por muestra, configurable por ejecución.
Se define `D` como el tiempo transcurrido entre la primera y la última muestra
de una ventana. Para cubrir al menos `D`, incluyendo ambos extremos:

`N = ceil(D / C) + 1`

La duración efectiva de una ventana de `N` muestras es `(N - 1) * C`. Cada
régimen elige una duración configurable (`D_solar`, `D_nb_idle`,
`D_nb_steady` o `D_nb_ramp`); no se fijan valores hasta conocer la cadencia y
los transitorios de interés.

Al confirmarse una transición, seleccionar inmediatamente las últimas `N`
muestras disponibles del activo y de la ejecución actuales. No esperar muestras
futuras para llenar una ventana más larga ni descartar el historial reciente.
Si aún no hay suficientes datos (arranque, hueco largo o cambio de ejecución),
marcar `insufficient_history` y no emitir una predicción como si fuera válida.
Si el modelo requiere longitudes uniformes, usar padding con máscara explícita
o modelos separados por régimen; documentar y probar la opción elegida.

Un cambio de régimen dentro de una ejecución no reinicia el buffer. Sí se
reinicia al cambiar `run_id` o `asset_id`, al detectar una discontinuidad
temporal superior al máximo configurable o al cambiar la versión del esquema.
Nunca se mezclan muestras de distintas ejecuciones.

## Particiones y generación de ventanas

- Asignar `train`, `validation` y `test` por `run_id` completo antes de generar
  ventanas. Usar agrupación adicional por activo o familia si se quiere medir
  generalización a activos no vistos.
- Mantener cada ejecución —incluidos el periodo sano, el inicio de degradación
  y el fallo, si existe— en una sola partición. No dividir una ejecución por
  el escenario o por la etiqueta de fallo: se perderían ventanas precursoras.
- Aplicar stride solo dentro de una ejecución y partición. Una ventana que
  exceda cualquiera de sus límites se rechaza; no se completa con datos de la
  siguiente ejecución.
- Ordenar por timestamp, comprobar unicidad y cadencia, y tratar huecos según
  el contrato de telemetría antes de construir ventanas.

## Objetivo y baseline

Separar dos problemas que no son intercambiables:

1. **Estimación de estado oculto:** estimar variables actuales como la
   temperatura de unión usando solo entradas permitidas. Comparar primero con
   un modelo térmico RC sencillo. La temperatura de unión verdadera del
   simulador no puede usarse como entrada del baseline.
2. **Pronóstico:** predecir la temperatura en `t + H` o si se alcanzará un
   umbral dentro del horizonte configurable `H`. El baseline de persistencia
   proyecta el último valor estimado causalmente disponible:
   `predicción(t + H) = estimación_disponible(t)`.

No presentar persistencia de `T_j(t)` como baseline operativo si `T_j` no está
medida ni estimada al momento de inferencia. Documentar el horizonte y el origen
de cada entrada del baseline. Las etiquetas futuras se calculan con verdad-
terreno solo fuera de la ruta de inferencia.

## Métricas y reglas de puntuación

- **Estimación/regresión:** informar MAE y RMSE frente a la verdad-terreno,
  por señal, perfil, régimen y escenario. No mezclar tareas de estimación
  actual con pronósticos a horizonte `H`.
- **Eventos térmicos:** definir una alarma como una predicción que supera el
  umbral configurado dentro de `H`. Contar verdaderos positivos, falsas alarmas
  y omisiones por evento; informar además falsas alarmas por hora de operación.
  Fijar la regla para agrupar alarmas consecutivas en un solo evento y el
  periodo de enfriamiento antes de evaluar.
- **Antelación:** para un evento detectado antes del fallo,
  `lead_time = t_fallo - t_primera_alarma`. Una alarma en o después del fallo es
  tardía y cuenta como omisión para la detección anticipada; no se reporta como
  antelación positiva.
- **Coste asimétrico:** reportar por separado coste de falsa alarma,
  omisión/alarma tardía y detección anticipada. Los costes o forma de la
  penalización se configuran y justifican; no asumir una penalización
  exponencial ni valores monetarios sin datos del operador.
- **RUL:** puntuar error de RUL solo en ejecuciones con fallo verdadero dentro
  del horizonte observado. Identificar esta métrica como evaluación de casos
  completos; las ejecuciones sin fallo son censuradas, no fallos con RUL cero.

Todos los resultados se reportan sobre ejecuciones de prueba no usadas para
entrenamiento ni ajuste de umbrales. Fijar semillas, guardar configuración y
reportar el número de ejecuciones y eventos evaluados.

## Configuración pendiente

La configuración de simulación debe versionar como mínimo:

```yaml
windowing:
  sampling_period_ms: 1000
  solar:
    irradiance_on_w_m2: null
    irradiance_off_w_m2: null
    debounce_s: null
    active_duration_s: null
    low_duration_s: null
  nb:
    ramp_threshold_kw_per_s: null
    debounce_s: null
    idle_duration_s: null
    steady_duration_s: null
    ramp_duration_s: null
  max_gap_s: null
  stride_s: null
evaluation:
  forecast_horizon_s: null
  thermal_threshold_c: null
  alarm_cooldown_s: null
```

Los `null` indican parámetros que deben acordarse antes de ejecutar la
evaluación; no son valores predeterminados utilizables.

## Criterios de aceptación

1. Pruebas deterministas cubren los umbrales, histéresis, debounce, datos
   ausentes y régimen `unknown`.
2. Se verifica la fórmula de `N`, la duración efectiva y la selección
   inmediata de historial disponible en cada transición.
3. Las pruebas demuestran que no se cruzan `run_id`, activo ni particiones y
   que una ventana incluye datos previos al inicio de una degradación dentro de
   su misma ejecución.
4. El baseline usa solo señales disponibles causalmente al inferir; ningún
   campo de `labels.jsonl` llega a las características.
5. Las métricas se reproducen con configuración y semilla guardadas, con
   conteo a nivel de evento para falsas alarmas, omisiones y antelación.
