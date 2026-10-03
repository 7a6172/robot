#ifndef POLYLINE_GENERATION_H
#define POLYLINE_GENERATION_H

#include <rclcpp/rclcpp.hpp>
#include <unordered_map>
#include <utils/math_utils.h>

#define POLYLINE_GEN_USE_DP 0
#define POLYLINE_GEN_USE_BDDA 1

using namespace std;

namespace polyline_generation
{
    class polyline_generator
    {
    public:
        polyline_generator() {};
        ~polyline_generator() {};

        tuple<bool, vector<pair<float, float>>, vector<pair<float, float>>> generate(const vector<pair<float, float>> &path_initial,
                                                                                     const int &width, const int &height, const float &resolu,
                                                                                     const int &sampling_grid_dist,
                                                                                     const float &min_obs_dist,
                                                                                     const float &polyline_sample_max_dist,
                                                                                     const int &polyline_sample_step,
                                                                                     const vector<float> &obs_dist_table);
    };
}

#endif