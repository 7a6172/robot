#include <utils/global_planner/backend_optimization.h>

namespace backend_optimization
{
    vector<point_constraint_rect> backend_optimizer::build_anisotropic_boundaries(const vector<pair<float, float>> &path_initial,
                                                                                  const int &width, const int &height, const float &resolu,
                                                                                  const int &sampling_grid_dist,
                                                                                  const float &min_obs_dist,
                                                                                  const vector<float> &obs_dist_table)
    {
        vector<point_constraint_rect> ret;
        ret.resize(path_initial.size(), {0.0, 0.0, 0.0, 0.0});

        // 每个点，八个末端
        std::vector<std::vector<pair<float, float>>> ray_endpoints(
            path_initial.size(),
            std::vector<pair<float, float>>(8, {0.0, 0.0}));

        // 方向向量
        std::vector<std::pair<float, float>> directions = {
            {0.0, 1.0}, {0.707, 0.707}, {1.0, 0.0}, {0.707, -0.707}, {0.0, -1.0}, {-0.707, -0.707}, {-1.0, 0.0}, {-0.707, 0.707}};

        // 八方向查找
        for (int i = 0; i < path_initial.size(); i++)
        {
            float x0 = path_initial[i].first;
            float y0 = path_initial[i].second;

            for (int d = 0; d < 8; d++)
            {
                float dx = directions[d].first;
                float dy = directions[d].second;

                float x = x0;
                float y = y0;

                int step = 0;

                while (step < MAX_SAMPLING_STEP)
                {
                    x += dx * sampling_grid_dist;
                    y += dy * sampling_grid_dist;

                    // 转换回整数索引
                    int xi = static_cast<int>(round(x));
                    int yi = static_cast<int>(round(y));

                    // 检查边界
                    if (xi < 0 || xi >= width || yi < 0 || yi >= height)
                    {
                        break;
                    }

                    int index = yi * width + xi;

                    // 检查边界
                    if (index < 0 || index >= obs_dist_table.size())
                    {
                        break;
                    }

                    if (obs_dist_table[index] < min_obs_dist)
                    {
                        break;
                    }

                    step++;
                }

                // 存储射线终点
                ray_endpoints[i][d] = {x - x0, y - y0};
            }
        }

        // 构造安全矩形
        for (int i = 0; i < path_initial.size(); i++)
        {
            point_constraint_rect bound;

            bound.xmax = INFINITY;
            bound.xmin = -INFINITY;
            bound.ymax = INFINITY;
            bound.ymin = -INFINITY;

            for (int d = 0; d < 8; d++)
            {
                if (ray_endpoints[i][d].first > 0)
                {
                    bound.xmax = std::min(bound.xmax, ray_endpoints[i][d].first);
                }
                else if (ray_endpoints[i][d].first < 0)
                {
                    bound.xmin = std::max(bound.xmin, ray_endpoints[i][d].first);
                }

                if (ray_endpoints[i][d].second > 0)
                {
                    bound.ymax = std::min(bound.ymax, ray_endpoints[i][d].second);
                }
                else if (ray_endpoints[i][d].second < 0)
                {
                    bound.ymin = std::max(bound.ymin, ray_endpoints[i][d].second);
                }
            }

            if (!std::isfinite(bound.xmax))
            {
                bound.xmax = 0;
            }

            if (!std::isfinite(bound.xmin))
            {
                bound.xmin = 0;
            }

            if (!std::isfinite(bound.ymax))
            {
                bound.ymax = 0;
            }

            if (!std::isfinite(bound.ymin))
            {
                bound.ymin = 0;
            }

            bound.xmin = std::abs(bound.xmin);
            bound.ymin = std::abs(bound.ymin);

            ret[i] = bound;
        }

        ret[0] = {0.0, 0.0, 0.0, 0.0};
        ret[ret.size() - 1] = {0.0, 0.0, 0.0, 0.0};

        // for (int i = 0; i < ret.size(); i++)
        // {
        //     ROS_WARN("id:%d xmin:%f xmax:%f ymin:%f ymax:%f", i,
        //              ret[i].xmin,
        //              ret[i].xmax,
        //              ret[i].ymin,
        //              ret[i].ymax);
        // }

        return ret;
    }

    tuple<bool, vector<pair<float, float>>> backend_optimizer::optimize(const vector<pair<float, float>> &path_initial,
                                                                        const int &width, const int &height, const float &resolu,
                                                                        const int &sampling_grid_dist,
                                                                        const float &min_obs_dist,
                                                                        const vector<float> &obs_dist_table)
    {
        tuple<bool, vector<pair<float, float>>> ret = {false, {}};
        vector<pair<float, float>> path_optimized;

        path_optimized.resize(path_initial.size(), {0, 0});

        if (path_initial.size() <= 2)
        {
            ret = {true, path_initial};

            return ret;
        }

        std::vector<std::pair<double, double>> raw_point2d;
        std::vector<point_constraint_rect> anchorpoints_lateralbound;

        anchorpoints_lateralbound = build_anisotropic_boundaries(
            path_initial, width, height, resolu,
            sampling_grid_dist, min_obs_dist, obs_dist_table);

        for (const auto &point : path_initial)
        {
            raw_point2d.emplace_back(point);
        }

        osqp_smoother smoother;

        std::vector<double> opt_x;
        std::vector<double> opt_y;

        if (smoother.solve(raw_point2d, anchorpoints_lateralbound, &opt_x, &opt_y))
        {
            size_t point_size = opt_x.size();

            for (size_t i = 0; i < point_size; ++i)
            {
                path_optimized[i] = {opt_x[i], opt_y[i]};
            }

            ret = {true, path_optimized};
        }

        return ret;
    }
}