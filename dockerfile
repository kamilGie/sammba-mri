# ==================================================================================================
# Stage 1: Building the environment with Conda, R, and RATS
# If new applications need to be added to the project,
# update this stage and then copy the appropriate binaries to the final image.
# ==================================================================================================
FROM continuumio/miniconda3 AS builder

WORKDIR /build

# Installation of system dependencies
RUN apt-get update && \
	apt-get install -y --no-install-recommends \
	curl \
	unzip && \
	apt-get clean && \
	rm -rf /var/lib/apt/lists/*

# Downloading and installing RATS
RUN curl -o /tmp/rats.zip https://iibi.uiowa.edu/sites/iibi.uiowa.edu/files/2023-03/rats.zip && \
	unzip /tmp/rats.zip -d /opt/rats && \
	rm /tmp/rats.zip

# Copying the environment file and creating the Conda environment
COPY sammba_environment.yml .

# Installing Python and R packages using Conda
RUN conda env create -f sammba_environment.yml && \
	conda install -y -n sammba -c conda-forge \
	jupyterlab \
	notebook \
	r-base \
	r-essentials \
	r-irkernel

# Packaging the Conda environment
RUN conda install -y -c conda-forge conda-pack && \
	conda-pack -n sammba -o /tmp/sammba.tar.gz

# ==================================================================================================
# Stage 2: Creating the final image
# The base image is large and contains tools like AFNI, SPM, ANTs.
# In this stage, we simply unpack the prepared environment.
# ==================================================================================================
FROM poldracklab/mriqc:latest

WORKDIR /workspace

# Copying the Conda environment and RATS
COPY --from=builder /tmp/sammba.tar.gz /opt/
COPY --from=builder /opt/rats /opt/rats

# Unpacking the Conda environment
RUN mkdir -p /opt/sammba && \
	tar -xzf /opt/sammba.tar.gz -C /opt/sammba && \
	rm /opt/sammba.tar.gz && \
	/opt/sammba/bin/conda-unpack

# Setting environment variables
ENV PATH="/opt/sammba/bin:/opt/rats/distribution 2:${PATH}"

# Exposing the port for Jupyter Lab
EXPOSE 8888

# Setting the default command
ENTRYPOINT ["jupyter", "lab", "--ip=0.0.0.0", "--no-browser", "--allow-root", "--LabApp.token=''"]

# Image author information
LABEL org.opencontainers.image.authors="gieras@student.agh.edu.pl"

