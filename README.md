# Agente de mantenimiento predictivo para electrónica de potencia

Demostrador de portfolio para el mantenimiento predictivo de inversores
solares Freesun de escala utility y cargadores de vehículos eléctricos de la
serie NB. El sistema generará telemetría sintética similar a SCADA, estimará la
degradación progresiva, investigará anomalías con agentes de Google ADK y
presentará recomendaciones trazables sujetas a una política de seguridad.

## Estado

- **Fase 1 — dominio e infografía:** completada. El informe está en
  [Telemetría Inversores Solares Industriales](docs/Telemetr%C3%ADa%20Inversores%20Solares%20Industriales.md).
- **Fase 2 — estado del arte y propuesta de modelo secuencial:** entregada.
  Consulta el [informe SOTA](docs/phase-2-sota.md) y las
  [decisiones de implementación](docs/phase-2-implementation-notes.md), además
  del [esquema de telemetría v1.0](docs/phase-2-versioned-telemetry-schema.md).
- **Demo/revisión objetivo:** 15 de enero de 2027.

La estimación supone unas 8–10 horas de trabajo individual por semana desde el
16 de noviembre de 2026, con una demo basada en datos sintéticos y acciones
administrativas y de control simuladas. Se reserva aproximadamente una semana
para integración; la falta de acceso a servicios de Google Cloud u observabilidad
no debe bloquear la demo local.

## Demo prevista

1. Generar perfiles reproducibles de telemetría Freesun y NB.
2. Inyectar degradación térmica gradual del IGBT, crecimiento de ESR del bus DC
   y caídas de resistencia de aislamiento relacionadas con la humedad.
3. Probar un modelo secuencial como predictor experimental e informar su
   rendimiento en escenarios sintéticos no usados durante el entrenamiento.
4. Enrutar las anomalías mediante un orquestador raíz y agentes especialistas
   térmicos y dieléctricos.
5. Aplicar una política de seguridad antes de cualquier acción. Jira, SAP y la
   limitación o el aislamiento de potencia son **simulaciones**: el proyecto no
   se conectará a equipos OT reales ni los controlará.
6. Mostrar en directo la telemetría, las predicciones, las derivaciones entre
   agentes, las decisiones de seguridad y la orden de trabajo simulada.

## Alcance inicial

- Señales principales: temperatura de unión estimada del IGBT, ESR del bus DC,
  resistencia de aislamiento a tierra y asimetría de corrientes de fase AC.
- Contexto: temperatura ambiente, humedad, irradiancia, carga/corriente,
  temperatura del disipador y familia del equipo.
- Comparar ventanas temporales para los perfiles solares suaves y las rampas
  térmicas de carga de vehículos eléctricos de 20–40 minutos.
- Mantener separados y comprobables la generación de datos, la evaluación del
  modelo, el razonamiento de agentes y la ejecución de acciones.

## Seguimiento

El repositorio contiene hitos e incidencias con fechas. El GitHub Project
asociado es el tablero de trabajo; al ser un proyecto individual, el desarrollo
se realiza directamente sobre `main`.

Consulta la [hoja de ruta](docs/roadmap.md) para ver el calendario, los criterios
de aceptación, las hipótesis y la condición de salida de la demo.
