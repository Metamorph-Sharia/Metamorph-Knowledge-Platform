# Airflow with the DAGs inside, for ECS (deploy/aws/ingestion/airflow.yaml), where nothing is bind-mounted.
# Locally compose.yaml runs the same base image with dags/ mounted instead. Built with dags/ as the context:
#   docker build -f docker/airflow.Dockerfile -t metamorph/airflow dags
FROM apache/airflow:2.10.5-python3.11
COPY --chown=airflow:root --exclude=**/__pycache__ . /opt/airflow/dags
