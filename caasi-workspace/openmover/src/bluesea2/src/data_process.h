#ifndef _DATA_PROCESS_
#define _DATA_PROCESS_
#include "parser.h"
#include <cmath>
#include <cstdint>
#include <vector>
#include <sensor_msgs/msg/laser_scan.hpp>

typedef struct
{
    unsigned short N;
    uint32_t ts[2];

    DataPoint points[0];

}DataPoints,*PDataPoints;

bool data_process(sensor_msgs::msg::LaserScan&);
int find(std::vector<RawData>a, int n, int x);
int autoGetFirstAngle(RawData raw, bool from_zero, std::vector<RawData>& raws, std::string &result);
bool whole_data_process(RawData raw, bool from_zero, int collect_angle, std::vector<RawData>& whole_datas, PDataPoints *data, int &size, char* result);
#endif
