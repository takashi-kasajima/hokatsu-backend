
FROM public.ecr.aws/lambda/python:3.10

RUN yum update -y && yum install -y java-1.8.0-openjdk

ENV JAVA_HOME=/usr/lib/jvm/jre-1.8.0-openjdk

ENV PATH=$JAVA_HOME/bin:$PATH

WORKDIR /var/task

# Setup Python environment
# Install PYTHON requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy function code to container
COPY ota.py .
# Set the entrypoint command for the Docker image
CMD [ "ota.lambda_handler" ]