FROM continuumio/miniconda3

# 1. Instalacja zależności systemowych z kompatybilnością Debian
RUN apt-get update && \
	DEBIAN_FRONTEND=noninteractive apt-get install -y \
	git \
	curl \
	tcsh \
	r-base \
	unzip \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*

# 2. Utworzenie środowiska conda z jawną specyfikacją kanałów
COPY . .
RUN conda env create -f sammba_environment.yml

# 3. Optymalizacja ścieżek dla Conda i AFNI
ENV PATH="/opt/conda/envs/sammba/bin:/root/abin:${PATH}"
SHELL ["/bin/bash", "-c"]

# 4. Instalacja AFNI z weryfikacją kompatybilności
RUN curl -O https://raw.githubusercontent.com/afni/afni/master/src/other_builds/OS_notes.linux_ubuntu_24_64_a_admin.txt && \
	grep -q "apt-get install" OS_notes.linux_ubuntu_24_64_a_admin.txt && \
	sed -i 's/sudo //g' OS_notes.linux_ubuntu_24_64_a_admin.txt && \
	bash OS_notes.linux_ubuntu_24_64_a_admin.txt

RUN curl -O https://afni.nimh.nih.gov/pub/dist/bin/misc/@update.afni.binaries && \
	tcsh @update.afni.binaries -package linux_ubuntu_24_64 -do_extras

# 5. Instalacja pakietów R z automatyzacją
RUN mkdir -p /root/R && \
	echo 'install.packages(c("pkg1", "pkg2"), repos="https://cloud.r-project.org")' > install_packages.R && \
	Rscript install_packages.R

# 6 pobieranie RAtS
RUN curl -o rats.zip https://iibi.uiowa.edu/sites/iibi.uiowa.edu/files/2023-03/rats.zip  
RUN unzip rats.zip -d /opt/rats
ENV PATH="/opt/rats/bin:${PATH}"

# 7. Bezpieczna konfiguracja Jupyter
RUN conda install -n sammba -c conda-forge jupyterlab notebook && \
	conda clean -afy

# 5.2 Oczyszczenie listy pakietów Apt
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

EXPOSE 8888

WORKDIR /workspace

ENTRYPOINT ["conda", "run", "-n", "sammba"]

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--LabApp.token=sammba"]
