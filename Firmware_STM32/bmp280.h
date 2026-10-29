#ifndef BMP280_H
#define BMP280_H

#include "stm32f4xx_hal_i2c.h"

// Adresse I2C (SDO à GND -> 0x76, SDO à VCC -> 0x77)
#define BMP280_ADDR         0x77

// Registres
#define BMP280_REG_ID        0xD0
#define BMP280_REG_RESET     0xE0
#define BMP280_REG_CTRL_MEAS 0xF4
#define BMP280_REG_CONFIG    0xF5
#define BMP280_REG_PRESS_MSB 0xF7
#define BMP280_REG_TEMP_MSB  0xFA

uint8_t BMP280_Init(I2C_HandleTypeDef *hi2c);
float   BMP280_GetTemperature(I2C_HandleTypeDef *hi2c);
float   BMP280_GetPressure(I2C_HandleTypeDef *hi2c);
float   BMP280_CalcAltitude(float pressure_pa, float sea_level_pressure_pa);

#endif
