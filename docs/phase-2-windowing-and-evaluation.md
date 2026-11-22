# Especificación v1: regímenes, ventanas y evaluación

## Alcance

Esta especificación define la lógica determinista que precede a la inferencia.
La familia del activo y su perfil se conocen por metadatos; no se infieren a
partir de la irradiancia. El detector de régimen, el buffer, la selección de
ventana y la evaluación no dependen de un LLM.

Los umbrales y duraciones se leen de una configuración versionada. Los valores
que dependen de resolución de sensores, activos o coste de mantenimiento quedan
pendientes de calibración; no se inventan como límites de seguridad.

La demo es un entorno sintético reproducible, no un gemelo digital validado.
Cada parámetro debe identificarse como dato de fabricante, referencia de norma,
literatura, supuesto de simulación o valor pendiente de verificar.

## Cadencia física y cadencia de telemetría

El paso interno del simulador y el intervalo de emisión de telemetría son
parámetros distintos. Un paso físico corto no implica que el sistema de
monitorización reciba una muestra con esa frecuencia.

El informe de parámetros propone como **escenarios candidatos que requieren
verificación de fuente**, no como requisito universal:

- Freesun: emisión cada 60 s en un escenario de resolución alta y cada 300 s
  como escenario SCADA documentado.
- NB: 30–60 s durante una sesión y 900 s en reposo; 10–30 s es una opción de
  monitorización más frecuente, no la cadencia estándar asumida.
- Simulación física: ensayar pasos separados de la telemetría (candidatos de
  1–10 s para Freesun y de 1–5 s durante carga NB). Su selección depende de la
  dinámica que efectivamente resuelva el modelo.

La cadencia de 1 Hz del esquema v1 se conserva como modo de desarrollo/prueba
configurable, no se presenta como adquisición SCADA real. El manifiesto de cada
ejecución guarda ambas cadencias, modo de perfil, resolución de origen y
procedencia. En NB, un intervalo de reposo de 900 s es una lectura programada,
no automáticamente un hueco de datos; la política de discontinuidad debe
comparar timestamps con el calendario de emisión esperado para el modo.

Para ventanas con cadencia variable, calcular cobertura con timestamps UTC,
no convertir a muestras mediante una única cadencia. La configuración debe
declarar el mínimo de observaciones requerido para cada modelo/ventana. Si la
implementación solo admite cadencia fija por ejecución, debe rechazar o marcar
explícitamente como no soportada una transición de cadencia; no interpolar
muestras futuras ni clasificar un periodo de reposo esperado como pérdida de
telemetría.

La muestra indica `next_expected_interval_ms`: el intervalo esperado después
de su timestamp según el estado operativo observado. El buffer compara el
tiempo real entre dos muestras con el intervalo esperado guardado en la muestra
anterior. Se permite el mayor entre el próximo intervalo esperado y `max_gap_s`;
un retraso por encima de ambos reinicia el historial. La cobertura de una ventana
se calcula con timestamps y su mínimo de muestras configurado por régimen. En
modo fijo, la configuración puede derivar este mínimo de la cadencia para
mantener compatibilidad con los ensayos existentes.

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

Para una cadencia fija `C` se define `D` como el tiempo transcurrido entre la
primera y la última muestra de una ventana. Para cubrir al menos `D`, incluyendo
ambos extremos:

`N = ceil(D / C) + 1`

La duración efectiva de una ventana de `N` muestras uniformes es `(N - 1) * C`.
En ventanas con cadencia variable, `N` no se calcula con una `C` ficticia: se
seleccionan muestras por límites temporales reales y se exige el mínimo de
observaciones configurado. Cada régimen elige una duración configurable
(`D_solar`, `D_nb_idle`, `D_nb_steady` o `D_nb_ramp`); no se fijan valores de
producción sin conocer resolución, transitorios y objetivo.

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

El baseline RC estima `T_j(t)` solo con telemetría observable y usa esa
estimación como predicción de persistencia `T_j(t + H)`. La evaluación de
pronóstico solo puntúa pares cuyo timestamp objetivo exacto existe en la
telemetría/verdad-terreno; no interpola ni consulta etiquetas durante la
inferencia. Si la cadencia variable no produce pares alineados, el informe
declara la métrica de pronóstico no disponible en lugar de fabricar muestras.

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
  exponencial ni valores monetarios sin datos del operador. La agregación queda
  desactivada si faltan pesos, unidad, fuente o justificación; la detección
  anticipada se informa como crédito por horas de antelación.
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
  physical_step_ms: null
  telemetry_schedule:
    # Cadencias candidatas por modo, no valores universales ni validados.
    freesun_high_resolution_ms: null
    freesun_scada_ms: null
    nb_session_ms: null
    nb_idle_ms: null
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
  minimum_samples:
    solar_active: null
    solar_low: null
    nb_idle: null
    nb_steady: null
    nb_ramp: null
evaluation:
  forecast_horizon_s: null
  thermal_threshold_c: null
  alarm_cooldown_s: null
```

Los `null` indican parámetros que deben acordarse antes de ejecutar la
evaluación; no son valores predeterminados utilizables.

La configuración persistida debe incluir también el paso físico, el calendario
de emisión aplicable, el mínimo de muestras por ventana y para cada umbral su
unidad, perfil/equipo, significado (aviso, protección sintética o EoL), fuente,
nivel de confianza y condición de validación.

## Criterios de aceptación

1. Pruebas deterministas cubren los umbrales, histéresis, debounce, datos
   ausentes y régimen `unknown`.
2. Se verifica la fórmula de `N` para cadencia uniforme y, para cadencia
   variable, cobertura temporal, mínimo de observaciones y calendario de
   emisión esperado. La selección en una transición usa inmediatamente el
   historial disponible; no espera muestras futuras.
3. Las pruebas demuestran que no se cruzan `run_id`, activo, versión de esquema
   ni particiones; una transición de régimen no borra el historial sano de la
   misma ejecución.
4. El baseline usa solo señales disponibles causalmente al inferir; ningún
   campo de `labels.jsonl` llega a las características. Estimación actual y
   pronóstico a horizonte se evalúan como objetivos diferentes.
5. Aviso predictivo, disparo sintético y EoL se configuran y etiquetan por
   separado. Un umbral candidato del informe no se activa como límite de
   protección ni se describe como calibrado para un equipo real.
6. La evaluación guarda semilla, cadencias, ventanas, umbrales y procedencia;
   se reproduce en ejecuciones de prueba reservadas y reporta errores de
   regresión y métricas de evento, incluidas falsas alarmas por hora, omisiones
   y antelación. Los costes asimétricos se reportan por separado y solo se
   agregan si sus ponderaciones están justificadas.
