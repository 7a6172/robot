#ifndef BACKEND_OPTIMIZATION_H
#define BACKEND_OPTIMIZATION_H

#include <rclcpp/rclcpp.hpp>
#include <utils/global_planner/osqp_smoother.h>
#include <utils/global_planner/osqp_utils.h>

using namespace std;

#define MAX_SAMPLING_STEP 100

namespace backend_optimization
{
    class backend_optimizer
    {
    public:
        backend_optimizer(){};
        ~backend_optimizer(){};

        tuple<bool, vector<pair<float, float>>> optimize(const vector<pair<float, float>> &path_initial,
                                                         const int &width, const int &height, const float &resolu,
                                                         const int &sampling_grid_dist,
                                                         const float &min_obs_dist,
                                                         const vector<float> &obs_dist_table);

    private:
        vector<point_constraint_rect> build_anisotropic_boundaries(const vector<pair<float, float>> &path_initial,
                                                                   const int &width, const int &height, const float &resolu,
                                                                   const int &sampling_grid_dist,
                                                                   const float &min_obs_dist,
                                                                   const vector<float> &obs_dist_table);
    };
}

#endif