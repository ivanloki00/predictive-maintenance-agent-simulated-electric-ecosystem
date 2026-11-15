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

**Siguiente paso:** completar la incidencia
[#3 — Especificar ventanas adaptativas y evaluación del modelo](https://github.com/ivanloki00/predictive-maintenance-agent-simulated-electric-ecosystem/issues/3).
Después, implementar `telemetry_sim.py` conforme al contrato. La ingesta debe
construir entradas mediante una lista permitida de campos; no basta con quitar
etiquetas de un objeto combinado.
