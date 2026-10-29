#include "bmp280.h"
#include <math.h>

static I2C_HandleTypeDef *bmp_i2c;
static uint8_t tx_buf[2];
static uint8_t rx_buf[32];

// Coefficients de calibration
static uint16_t dig_T1;
static int16_t  dig_T2, dig_T3;
static uint16_t dig_P1;
static int16_t  dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;
static int32_t t_fine;

// Attente passive sur le statut I2C identique à celle du LM75
static uint8_t I2C_Wait(I2C_HandleTypeDef *hi2c, uint32_t timeout_cycles) {
    volatile uint32_t timeout = timeout_cycles;
    while (hi2c->status == I2C_BUSY) {
        if (--timeout == 0) {
            hi2c->status = I2C_ERROR;
            break;
        }
    }
    return (hi2c->status == I2C_OK);
}

// Lecture d'un registre
static uint8_t ReadReg(uint8_t reg) {
    uint8_t data = 0;
    tx_buf[0] = reg;
    bmp_i2c->status = I2C_BUSY;
    HAL_I2C_Master_Transmit_IT(bmp_i2c, BMP280_ADDR, tx_buf, 1, 0);
    if (!I2C_Wait(bmp_i2c, 100000)) return 0;
    bmp_i2c->status = I2C_BUSY;
    HAL_I2C_Master_Receive_IT(bmp_i2c, BMP280_ADDR, &data, 1, 0);
    I2C_Wait(bmp_i2c, 100000);
    return data;
}

// Écriture d'un registre
static void WriteReg(uint8_t reg, uint8_t val) {
    tx_buf[0] = reg;
    tx_buf[1] = val;
    bmp_i2c->status = I2C_BUSY;
    HAL_I2C_Master_Transmit_IT(bmp_i2c, BMP280_ADDR, tx_buf, 2, 0);
    I2C_Wait(bmp_i2c, 100000);
}

// Lecture de plusieurs octets
static void ReadBytes(uint8_t reg, uint8_t *buf, uint8_t len) {
    tx_buf[0] = reg;
    bmp_i2c->status = I2C_BUSY;
    HAL_I2C_Master_Transmit_IT(bmp_i2c, BMP280_ADDR, tx_buf, 1, 0);
    if (!I2C_Wait(bmp_i2c, 100000)) return;
    bmp_i2c->status = I2C_BUSY;
    HAL_I2C_Master_Receive_IT(bmp_i2c, BMP280_ADDR, buf, len, 0);
    I2C_Wait(bmp_i2c, 100000);
}

// Lecture des coefficients de calibration (adresses 0x88 à 0x9F)
static void ReadCalibration(void) {
    uint8_t buf[24];
    ReadBytes(0x88, buf, 24);
    dig_T1 = buf[0] | (buf[1] << 8);
    dig_T2 = buf[2] | (buf[3] << 8);
    dig_T3 = buf[4] | (buf[5] << 8);
    dig_P1 = buf[6] | (buf[7] << 8);
    dig_P2 = buf[8] | (buf[9] << 8);
    dig_P3 = buf[10] | (buf[11] << 8);
    dig_P4 = buf[12] | (buf[13] << 8);
    dig_P5 = buf[14] | (buf[15] << 8);
    dig_P6 = buf[16] | (buf[17] << 8);
    dig_P7 = buf[18] | (buf[19] << 8);
    dig_P8 = buf[20] | (buf[21] << 8);
    dig_P9 = buf[22] | (buf[23] << 8);
}

// Compensation de la température (retourne température en centième de degrés)
static int32_t compensate_T(int32_t adc_T) {
    int32_t var1, var2;
    var1 = (((adc_T >> 3) - ((int32_t)dig_T1 << 1)) * (int32_t)dig_T2) >> 11;
    var2 = (((((adc_T >> 4) - (int32_t)dig_T1) * ((adc_T >> 4) - (int32_t)dig_T1)) >> 12) * (int32_t)dig_T3) >> 14;
    t_fine = var1 + var2;
    return (t_fine * 5 + 128) >> 8;
}

// Compensation de la pression (retourne pression en Pascals / 256)
static uint32_t compensate_P(int32_t adc_P) {
    int64_t var1, var2, p;
    var1 = (int64_t)t_fine - 128000;
    var2 = var1 * var1 * (int64_t)dig_P6;
    var2 = var2 + ((var1 * (int64_t)dig_P5) << 17);
    var2 = var2 + (((int64_t)dig_P4) << 35);
    var1 = ((var1 * var1 * (int64_t)dig_P3) >> 8) + ((var1 * (int64_t)dig_P2) << 12);
    var1 = (((((int64_t)1) << 47) + var1)) * (int64_t)dig_P1 >> 33;
    if (var1 == 0) return 0;
    p = 1048576 - adc_P;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = ((int64_t)dig_P9 * (p >> 13) * (p >> 13)) >> 25;
    var2 = ((int64_t)dig_P8 * p) >> 19;
    p = ((p + var1 + var2) >> 8) + ((int64_t)dig_P7 << 4);
    return (uint32_t)p;
}

// ------------ initialisation du capteur ---------------
uint8_t BMP280_Init(I2C_HandleTypeDef *hi2c) {
    bmp_i2c = hi2c;
    uint8_t id = ReadReg(BMP280_REG_ID);
    if (id != 0x58) return 0;
    WriteReg(BMP280_REG_RESET, 0xB6);
    HAL_Delay(10);
    ReadCalibration();
    WriteReg(BMP280_REG_CTRL_MEAS, 0x27);
    WriteReg(BMP280_REG_CONFIG, 0x00);
    HAL_Delay(100);
    return 1;
}
//--------------les fonctions publiques de mesure-------------------
float BMP280_GetTemperature(I2C_HandleTypeDef *hi2c) {
    (void)hi2c;
    uint8_t buf[3];
    ReadBytes(BMP280_REG_TEMP_MSB, buf, 3);
    int32_t adc_T = ((int32_t)buf[0] << 12) | ((int32_t)buf[1] << 4) | (buf[2] >> 4);
    int32_t T = compensate_T(adc_T);
    return T / 100.0f;
}

float BMP280_GetPressure(I2C_HandleTypeDef *hi2c) {
    (void)hi2c;
    uint8_t buf[3];
    ReadBytes(BMP280_REG_PRESS_MSB, buf, 3);
    int32_t adc_P = ((int32_t)buf[0] << 12) | ((int32_t)buf[1] << 4) | (buf[2] >> 4);
    uint32_t P = compensate_P(adc_P);
    return P / 256.0f; // Pascals
}

float BMP280_CalcAltitude(float pressure_pa, float sea_level_pressure_pa) {
    return 44330.0f * (1.0f - powf(pressure_pa / sea_level_pressure_pa, 0.1903f));
}
