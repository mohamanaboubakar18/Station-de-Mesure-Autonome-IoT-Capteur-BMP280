#include "stm32f4xx_hal_msp.h"
#include "stm32f4xx_hal_gpio.h"
#include "stm32f4xx_hal_tim.h"
#include "stm32f4xx_hal_uart.h"
#include "stm32f4xx_hal_i2c.h"
#include "leds.h"
#include "sw.h"
#include "lm75.h"
#include "bmp280.h"
#include "stm32f4xx_hal.h"
#include <string.h>
#include <stdio.h>
#include <sys/types.h>

// Handles globaux
TIM_HandleTypeDef htim3;
TIM_HandleTypeDef htim5;
UART_HandleTypeDef huart2;
UART_HandleTypeDef huart1;
I2C_HandleTypeDef hi2c1;

uint8_t buf[5];
uint8_t input_char;
float lm75_temp_f;

// Stubs système
int _close(int file) { return -1; }
int _fstat(int file, void *st) { return -1; }
int _isatty(int file) { return 1; }
int _lseek(int file, int ptr, int dir) { return 0; }
int _read(int file, char *ptr, int len) { return 0; }
int _write(int file, char *ptr, int len) { return len; }
void _exit(int status) { while(1); }
int _kill(int pid, int sig) { return -1; }
int _getpid(void) { return 1; }

extern char end;
static char *heap_end = 0;
caddr_t _sbrk(int incr) {
    if (heap_end == 0) heap_end = &end;
    char *prev = heap_end;
    if (heap_end + incr > (char*)0x20020000) return (caddr_t)-1;
    heap_end += incr;
    return (caddr_t)prev;
}

// Callbacks
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin) { (void)GPIO_Pin; }
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart == &huart2) {
        input_char = huart2.Instance->DR;
        HAL_UART_Receive_IT(&huart2, &input_char, 1);
    }
}
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim) { (void)htim; }

int main(void) {
    HAL_Init();
    HAL_MspInit();

    // I2C1 (identique à celui du LM75)
    hi2c1.Instance = I2C1;
    hi2c1.Init.ClockSpeed = 400000;
    HAL_I2C_Init(&hi2c1);

    // UART2
    huart2.Instance = USART2;
    huart2.Init.BaudRate = 115200;
    huart2.Init.WordLength = UART_WORDLENGTH_8B;
    huart2.Init.StopBits = UART_STOPBITS_1;
    huart2.Init.Parity = UART_PARITY_NONE;
    HAL_UART_Init(&huart2);
    HAL_UART_Receive_IT(&huart2, &input_char, 1);   // réception d'un caractère

    //UART1
    huart1.Instance = USART1;
    huart1.Init.BaudRate = 9600;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    HAL_UART_Init(&huart1);
    HAL_UART_Receive_IT(&huart1, &input_char, 1);

    HAL_Delay(100);


    // Initialisation du BMP280
   if (!BMP280_Init(&hi2c1)) {
        uart_printf(&huart2, (uint8_t*)"Capteur BMP280 non detecte\r\n");
        while(1);
    }
    uart_printf(&huart2, (uint8_t*)"Capteur BMP280 prêt\r\n");

    // Variable pour l'affichage périodique du BMP280
    uint32_t last_bmp_print = 0;

    while (1) {

// Lecture et affichage du BMP280 toutes les 2 secondes
        if ((HAL_GetTick() - last_bmp_print) >= 2000) {
            float bmp_temp = BMP280_GetTemperature(&hi2c1);
            float bmp_press = BMP280_GetPressure(&hi2c1);
            float bmp_alt = BMP280_CalcAltitude(bmp_press, 101325.0f);
            uart_printf(&huart2, (uint8_t*)"BMP280: T=%f C  P=%f hPa  Alt=%f m\r\n", bmp_temp, bmp_press/100.0f, bmp_alt);
            uart_printf(&huart1, (uint8_t*)"BMP280: T=%f C  P=%f hPa  Alt=%f m\r\n", bmp_temp, bmp_press/100.0f, bmp_alt);
            last_bmp_print = HAL_GetTick();
        }

        HAL_Delay(100);
    }
}


