#ifndef CRC8_MAXIM_H
#define CRC8_MAXIM_H

#include <cstdint>  // ROS 1 pulled this in via ros/ros.h; the CRC itself needs nothing else.

uint8_t crc8_maxim(uint8_t *buffer, uint8_t size);

#endif