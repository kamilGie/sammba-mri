FROM ubuntu:jammy-20240125 as downloader
RUN apt-get update && \
	DEBIAN_FRONTEND=noninteractive \
	apt-get install -y --no-install-recommends \
	binutils \
	bzip2 \
	ca-certificates \
	curl \
	unzip && \
	apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# FSL
RUN curl -sSL https://fsl.fmrib.ox.ac.uk/fsldownloads/fsl-5.0.11-centos7_64.tar.gz | tar zxv --no-same-owner -C /opt \
	--exclude='fsl/doc' \
	--exclude='fsl/refdoc' \
	--exclude='fsl/python/oxford_asl' \
	--exclude='fsl/data/possum' \
	--exclude='fsl/data/first' \
	--exclude='fsl/data/mist' \
	--exclude='fsl/data/atlases' \
	--exclude='fsl/data/xtract_data' \
	--exclude='fsl/extras/doc' \
	--exclude='fsl/extras/man' \
	--exclude='fsl/extras/src' \
	--exclude='fsl/src' \
	--exclude='fsl/tcl'

# AFNI
RUN mkdir -p /opt/afni-latest \
	&& curl -fsSL --retry 5 https://afni.nimh.nih.gov/pub/dist/tgz/linux_openmp_64.tgz \
	| tar -xz -C /opt/afni-latest --strip-components 1 \
	--exclude "linux_openmp_64/*.gz" \
	--exclude "linux_openmp_64/funstuff" \
	--exclude "linux_openmp_64/shiny" \
	--exclude "linux_openmp_64/afnipy" \
	--exclude "linux_openmp_64/lib/RetroTS" \
	--exclude "linux_openmp_64/lib_RetroTS" \
	--exclude "linux_openmp_64/meica.libs" \
	# Keep only what we use
	&& find /opt/afni-latest -type f -not \( \
	-name "3dAutomask" \
	-or -name "3dcalc" \
	-or -name "3dFWHMx" \
	-or -name "3dinfo" \
	-or -name "3dmaskave" \
	-or -name "3dSkullStrip" \
	-or -name "3dTnorm" \
	-or -name "3dToutcount" \
	-or -name "3dTqual" \
	-or -name "3dTshift" \
	-or -name "3dTstat" \
	-or -name "3dUnifize" \
	-or -name "3dvolreg" \
	-or -name "@compute_gcor" \
	-or -name "afni" \
	\) -delete



# Source Image
FROM nipreps/miniconda:py39_2403.0

ARG DEBIAN_FRONTEND=noninteractive
ENV LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:${CONDA_PATH}/lib"

# Configure PPAs for libpng12 and libxp6
RUN GNUPGHOME=/tmp gpg --keyserver hkps://keyserver.ubuntu.com --no-default-keyring --keyring /usr/share/keyrings/linuxuprising.gpg --recv 0xEA8CACC073C3DB2A \
	&& GNUPGHOME=/tmp gpg --keyserver hkps://keyserver.ubuntu.com --no-default-keyring --keyring /usr/share/keyrings/zeehio.gpg --recv 0xA1301338A3A48C4A \
	&& echo "deb [signed-by=/usr/share/keyrings/linuxuprising.gpg] https://ppa.launchpadcontent.net/linuxuprising/libpng12/ubuntu jammy main" > /etc/apt/sources.list.d/linuxuprising.list \
	&& echo "deb [signed-by=/usr/share/keyrings/zeehio.gpg] https://ppa.launchpadcontent.net/zeehio/libxp/ubuntu jammy main" > /etc/apt/sources.list.d/zeehio.list

# Dependencies for AFNI; requires a discontinued multiarch-support package from bionic (18.04)
RUN apt-get update -qq \
	&& apt-get install -y -q --no-install-recommends \
	git\
	ed \
	gsl-bin \
	libglib2.0-0 \
	libglu1-mesa-dev \
	libglw1-mesa \
	libgomp1 \
	libjpeg62 \
	libpng12-0 \
	libxm4 \
	libxp6 \
	netpbm \
	tcsh \
	xfonts-base \
	xvfb \
	&& curl -sSL --retry 5 -o /tmp/multiarch.deb http://archive.ubuntu.com/ubuntu/pool/main/g/glibc/multiarch-support_2.27-3ubuntu1.5_amd64.deb \
	&& dpkg -i /tmp/multiarch.deb \
	&& rm /tmp/multiarch.deb \
	&& apt-get install -f \
	&& apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
	&& gsl2_path="$(find / -name 'libgsl.so.19' || printf '')" \
	&& if [ -n "$gsl2_path" ]; then \
	ln -sfv "$gsl2_path" "$(dirname $gsl2_path)/libgsl.so.0"; \
	fi \
	&& ldconfig

# Install FSL
ENV FSL_DIR="/opt/fsl"
COPY --from=downloader /opt/fsl ${FSL_DIR}
ENV FSLDIR="/opt/fsl" \
	PATH="/opt/fsl/bin:$PATH" \
	FSLOUTPUTTYPE="NIFTI_GZ" \
	FSLMULTIFILEQUIT="TRUE" \
	FSLTCLSH="/opt/fsl/bin/fsltclsh" \
	FSLWISH="/opt/fsl/bin/fslwish" \
	FSLLOCKDIR="" \
	FSLMACHINELIST="" \
	FSLREMOTECALL="" \
	FSLGECUDAQ="cuda.q" \
	POSSUMDIR="/opt/fsl" \
	LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:/opt/fsl"

# Install AFNI
ENV AFNI_DIR="/opt/afni"
COPY --from=downloader /opt/afni-latest ${AFNI_DIR}
ENV PATH="${AFNI_DIR}:$PATH" \
	AFNI_IMSAVE_WARNINGS="NO" \
	AFNI_MODELPATH="${AFNI_DIR}/models" \
	AFNI_TTATLAS_DATASET="${AFNI_DIR}/atlases" \
	AFNI_PLUGINPATH="${AFNI_DIR}/plugins"

# Install Rats
RUN curl -o /tmp/rats.zip https://iibi.uiowa.edu/sites/iibi.uiowa.edu/files/2023-03/rats.zip && \
	unzip /tmp/rats.zip -d /opt/rats && \
	rm /tmp/rats.zip
ENV PATH="/opt/rats/distribution 2:${PATH}"

# Install Python libraries
ENV CONDA_PATH=/opt/conda
COPY sammba_environment.yml .
RUN micromamba install -n base -c conda-forge \
	--yes \
	--file sammba_environment.yml \
	micromamba \
	jupyterlab notebook \
	r-base r-essentials r-irkernel \
	ants=2.5 \
	conda-pack \
	&& micromamba clean --all --yes --locks \
	&& sync \
	&& ldconfig
ENV PATH=${CONDA_PATH}/bin:$PATH

# Unless otherwise specified each process should only use one thread - nipype will handle parallelization
ENV MKL_NUM_THREADS=1 OMP_NUM_THREADS=1  NUMEXPR_MAX_THREADS=1

# Helps in minimizing the image size.
RUN apt update && apt install --no-install-recommends -y libtiff5 libpng16-16 && ldconfig

# Defaults
EXPOSE 8888
WORKDIR /workspace
ENTRYPOINT ["jupyter", "lab", "--ip=0.0.0.0", "--no-browser", "--allow-root", "--LabApp.token=''"]

# Image author information
ARG BUILD_DATE
ARG VCS_REF
LABEL org.label-schema.build-date=$BUILD_DATE \
	org.label-schema.name="Sammba" \
	org.opencontainers.image.authors="gieras@student.agh.edu.pl" \
	org.label-schema.description="Sammba - small mammals brain MRI" \
	org.label-schema.vcs-ref=$VCS_REF
