# Station-de-Mesure-Autonome-IoT-Capteur-BMP280
Projet académique de conception de bout en bout d'un système d'acquisition de données environnementales (température, pression atmosphérique, altitude) incluant une transmission filaire et sans fil. Projet réalisé en binôme (Mohaman Aboubakar Garba / Mabaissa Dit Malaye Barnabas).

<img width="856" height="392" alt="image" src="https://github.com/user-attachments/assets/99f309b9-f53c-405f-aa3e-7dc533ca8fb5" />

# Architecture et Technologies
- Hardware : Microcontrôleur STM32 Nucleo F411RE (ARM Cortex-M4, 100 MHz), capteur environnemental BMP280, Grove Base Shield, modules de transmission radio Zigbee.
- Firmware (C / HAL) : Développement sous STM32CubeIDE (configuration de l'I2C1 et des USART1/2). Lecture du capteur en mode Normal (t_standby 0.5 ms, suréchantillonnage x1) via les registres d'étalonnage (0x88 à 0xA1) et de données brutes (0xF7 à 0xFC).
- Communication : Transmission de la chaîne formatée (T=X;P=Y;A=Z) de façon simultanée via filaire USB/ST-Link (USART2 à 115200 bauds) et sans fil point-à-point via Zigbee (USART1 à 9600 bauds).
- Software (Python / Tkinter) : Interface Homme-Machine (IHM) interactive affichant des courbes glissantes de 50 points en temps réel. Elle intègre des indicateurs statistiques (Min/Max/Moyenne), une base de données locale SQLite horodatée, et une fonction d'export CSV.

# Installation et Câblage
1- Insérer le Grove Base Shield sur les connecteurs de la carte STM32 Nucleo.   
2- Connecter le capteur BMP280 sur un port I2C (SDA/SCL) du shield.   
3- Brancher le module Zigbee émetteur sur le port UART du shield (broches PA9=TX et PA10=RX correspondant à l'USART1).   
4- Alimenter la Nucleo via le câble USB relié au PC.   
5- Brancher le module Zigbee récepteur sur le PC via un adaptateur USB-série pour générer un port COM virtuel.   
6- Flasher le firmware sur la STM32 via la sonde ST-Link intégrée.   
7- Lancer l'IHM Python, sélectionner le port COM approprié (ST-Link ou Zigbee) avec son baudrate, et cliquer sur Connecter.   

# Logique de Traitement et Compétences Mises en Œuvre
La fiabilité du système repose sur la compensation mathématique effectuée directement dans le firmware : le microcontrôleur lit les coefficients de calibrage d'usine stockés dans la ROM du BMP280 (dig_T1 à dig_P9) pour convertir les données ADC brutes en grandeurs physiques. Ces données permettent à l'IHM d'afficher des valeurs avec une haute stabilité. Le code source gère les interruptions matérielles (fonctions Callbacks UART/EXTI) pour assurer l'acquisition I2C fluide sans être bloqué par les transmissions radio.  
