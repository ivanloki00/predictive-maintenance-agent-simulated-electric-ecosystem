# Decisiones de implementación de la Fase 2

## Estado e interpretación

El informe SOTA está en [phase-2-sota.md](phase-2-sota.md). Es una propuesta de
arquitectura y una síntesis bibliográfica, no una prueba de que los modelos
propuestos se hayan entrenado o validado con datos de campo Freesun/NB.

Las cifras de precisión, los coeficientes específicos de materiales y las
estimaciones de vida útil restante deben considerarse sin verificar hasta
comprobar la fuente, los datos, las condiciones operativas y el método de
evaluación. El simulador puede probar si un método recupera la verdad-terreno
que él mismo generó; no puede demostrar precisión en campo.

## Decisiones para el producto mínimo viable

- **Estimación de temperatura:** generar la temperatura de unión oculta a
  partir de un modelo térmico RC sencillo y documentado. Empezar por este
  baseline físico o ingenuo; compararlo con un LSTM en escenarios reservados
  antes de considerar PINN, atención o arquitecturas convolucionales.
- **Ventanas adaptativas:** seleccionar duraciones acotadas mediante lógica
  determinista de régimen operativo (perfil solar, reposo o transitorio de
  carga NB). Registrar tanto la duración como el número de muestras. No delegar
  el muestreo ni las decisiones de protección a un agente LLM.
- **Degradación del aislamiento:** usar como mecanismo sintético un acumulador
  configurable de exposición a humedad. Una formulación inspirada en Peck es
  una hipótesis, no una ley de vida útil calibrada sin parámetros y evidencia
  específicos del material.
- **Extracción de tendencia:** comparar primero un estimador simple de
  baseline/tendencia; añadir STL solo si resulta útil para la cadencia y
  estacionalidad generadas.
- **Evaluación:** separar ejecuciones o escenarios completos en orden temporal
  para evitar fuga entre ventanas solapadas. Informar el error de temperatura,
  falsas alarmas y omisiones, antelación de detección y coste relativo de
  predicciones tempranas frente a tardías. Informar RUL solo cuando el
  simulador defina un umbral y un instante de fallo verdaderos.
- **Límite de los agentes:** el código convencional gestiona telemetría,
  selección de régimen, predicción y comprobaciones de política. Los agentes
  ADK explican la evidencia de eventos y solicitan acciones simuladas; no
  emiten órdenes a equipos reales.

## Contrato de telemetría y siguiente paso

El contrato v1.0 y sus ejemplos están en
[phase-2-versioned-telemetry-schema.md](phase-2-versioned-telemetry-schema.md).
Separa las muestras observables del archivo de etiquetas, asigna las
particiones por ejecución y especifica señales y valores ausentes. La cadencia
de 1 Hz se plantea como una configuración inicial de la demo, no como estándar
SCADA universal.

## Implementación de la incidencia #3 por fases

La lógica determinista reutilizable está en el paquete
`predictive_maintenance` y sus pruebas se ejecutan con
`python -m unittest discover -s tests -v`. Para generar un ejemplo reproducible
fuera del repositorio:

```powershell
python -m predictive_maintenance.demo --output C:\temp\predictive-maintenance-demo --seed 42
```

El comando escribe `telemetry.jsonl`, `labels.jsonl`, `manifest.json`,
`windows.jsonl` y `evaluation.json`. La cadencia, los umbrales, las duraciones,
el stride y los parámetros RC del demo son explícitos y se guardan en los
artefactos; tienen estatus `synthetic_unvalidated` y no son valores recomendados
para activos reales. Las configuraciones de las primitivas se pueden sustituir
al llamar directamente a las funciones de simulación y ventana.

1. **Regímenes y ventanas:** implementados clasificadores solares con
   histéresis/debounce y NB con detección inmediata de rampas, más una selección
   temporal acotada que marca `insufficient_history` y aplica stride, con opción
   de selección forzada en una transición. El pipeline procesa cada ejecución
   después de asignar sus particiones; el buffer no cruza ejecución, activo,
   perfil, esquema ni partición. Las muestras solo aceptan campos de telemetría
   y características incluidos en la lista permitida.
2. **Particiones:** implementada la asignación cronológica determinista de
   `run_id` completos a `train`, `validation` y `test`, antes de construir
   ventanas. No realiza todavía agrupación de generalización por familia o
   activo.
3. **Evaluación:** implementados MAE/RMSE, puntuación de alarmas por evento con
   cooldown, antelación, omisiones, alarmas tardías y falsas alarmas por hora,
   desglosados por perfil/escenario; la regresión se desglosa además por régimen
   operativo. El MAE de RUL se limita a ejecuciones con fallo observado. Los
   costes asimétricos son opcionales, requieren pesos, unidad, fuente y
   justificación; el demo no agrega costes sin esos datos. El baseline RC usa
   solo señales observables y consulta las etiquetas por separado. Separa la
   regresión de estado actual del pronóstico de persistencia a `t + H`, evaluado
   solo si existe una muestra objetivo con timestamp exacto.
4. **Entorno sintético:** `predictive_maintenance.simulator` genera perfiles
   Freesun/NB con semilla, degradación configurable, paso físico separado de la
   cadencia emitida, etiquetas futuras y un manifiesto de particiones. Admite
   intervalos NB sintéticos distintos durante sesión y reposo; cada muestra
   declara el próximo intervalo esperado y el buffer solo reinicia el historial
   si el hueco excede tanto ese intervalo como el `max_gap_s` configurado. Las
   ventanas usan cobertura UTC y mínimo de observaciones por régimen. Esta
   capacidad no verifica las cadencias candidatas del informe ni acredita una
   configuración de equipo real. La integración física aún mantiene la carga
   observada durante los subpasos entre emisiones; los eventos operativos que
   ocurran dentro de un intervalo largo no se resuelven con fidelidad física.
5. **Hitos sintéticos:** aviso predictivo objetivo, evento de protección
   sintético y fin de vida tienen fracciones configurables y marcas temporales
   separadas, independientes de la marca de fallo. Son fracciones de progreso
   interno no validadas; la fecha objetivo de aviso no representa una predicción
   realizada. No se usan los candidatos de la página 14 como límites reales.
   **Pendiente:** cadencias Freesun/NB verificadas en fuentes primarias,
   cobertura térmica e higrotérmica a escala adecuada, modelo LSTM/PINN, datos
   de campo, calibración física y agrupación de generalización por activo. El
   baseline de persistencia y las etiquetas sintéticas no demuestran precisión
   en equipos reales.

El diseño y sus criterios completos siguen en
[phase-2-windowing-and-evaluation.md](phase-2-windowing-and-evaluation.md).
La incidencia
[#3 — Refinar ventanas y evaluación sintética Freesun/NB con supuestos trazables](https://github.com/ivanloki00/predictive-maintenance-agent-simulated-electric-ecosystem/issues/3)
debe permanecer abierta hasta completar los criterios de aceptación restantes
anteriores; la integración básica con el simulador ya está disponible.
