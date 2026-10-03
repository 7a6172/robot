#include <navigation/utils/global_planner/polyline_generation.h>

namespace polyline_generation
{
    tuple<bool, vector<pair<float, float>>, vector<pair<float, float>>> polyline_generator::generate(const vector<pair<float, float>> &path_initial,
                                                                                                     const int &width, const int &height, const float &resolu,
                                                                                                     const int &sampling_grid_dist,
                                                                                                     const float &min_obs_dist,
                                                                                                     const float &polyline_sample_max_dist,
                                                                                                     const int &polyline_sample_step,
                                                                                                     const vector<float> &obs_dist_table)
    {
        vector<pair<float, float>> path_polyline;
        tuple<bool, vector<pair<float, float>>, vector<pair<float, float>>> ret = {false, path_initial, path_polyline};

        size_t n = path_initial.size();

        if (n < 2)
        {
            // ROS_ERROR("折线化失败。");

            return ret;
        }

        float polyline_expected_dist = polyline_sample_max_dist;

        float path_dist = 0.0f;

        for (int i = 1; i < n; i++)
        {
            float x0 = path_initial[i - 1].first * resolu;
            float y0 = path_initial[i - 1].second * resolu;
            float x1 = path_initial[i].first * resolu;
            float y1 = path_initial[i].second * resolu;
            path_dist += std::sqrt(
                std::pow(x1 - x0, 2) + std::pow(y1 - y0, 2));
        }

        polyline_expected_dist = std::min(path_dist / 2.0f, polyline_expected_dist);

        int polyline_expected_sample_step = polyline_sample_step;

        if (polyline_expected_sample_step >= n)
        {
            polyline_expected_sample_step = 1;
        }

        path_polyline.clear();

        float dist_k = 2.0;

#if POLYLINE_GEN_USE_DP
        unordered_map<int, unordered_map<int, float>> dp;
        unordered_map<int, unordered_map<int, int>> prev;

        dp[0][0] = 0;
        dp[1][0] = 0;

        for (int i = 0; i < n; i++)
        {
            if (i < n - 1)
            {
                dp[i + 1][i] = 0;
            }

            prev[0][i] = -1;
        }

        for (int i = 1; i < n; i++)
        {
            for (int j = i - 1; j >= 0; j -= polyline_expected_sample_step)
            {
                float x0 = path_initial[j].first * resolu;
                float y0 = path_initial[j].second * resolu;
                float x1 = path_initial[i].first * resolu;
                float y1 = path_initial[i].second * resolu;

                float dist = hypot(x1 - x0, y1 - y0);

                if (dist > polyline_expected_dist)
                {
                    break;
                }

                if (!is_segment_no_collision(x0, y0, x1, y1, sampling_grid_dist, width, height, resolu, min_obs_dist, obs_dist_table))
                {
                    continue;
                }

                for (int k = i + 1; k < n; k += polyline_expected_sample_step)
                {
                    float x2 = path_initial[k].first * resolu;
                    float y2 = path_initial[k].second * resolu;

                    float dist_next = hypot(x2 - x1, y2 - y1);

                    if (dist_next > polyline_expected_dist)
                    {
                        break;
                    }

                    if (!is_segment_no_collision(x1, y1, x2, y2, sampling_grid_dist, width, height, resolu, min_obs_dist, obs_dist_table))
                    {
                        continue;
                    }

                    // ROS_WARN("j: %d, i: %d, k: %d", j, i, k);

                    if (dp[i].find(j) == dp[i].end())
                    {
                        continue;
                    }

                    float dx1 = x1 - x0;
                    float dy1 = y1 - y0;
                    float dx2 = x2 - x1;
                    float dy2 = y2 - y1;
                    float dot_product = dx1 * dx2 + dy1 * dy2;
                    float cross_product = dx1 * dy2 - dy1 * dx2;
                    float angle = abs(atan2(abs(cross_product), dot_product));
                    // angle = angle < (10.0f * M_PI / 180.0f) ? 0 : angle;
                    float penalty = abs(dist_next - polyline_expected_dist);
                    float penalty_val = dist_k * penalty;

                    if (dp[i][j] + angle - penalty_val > dp[k][i])
                    {
                        dp[k][i] = dp[i][j] + angle - penalty_val;
                        prev[k][i] = j;
                    }
                }
            }
        }

        float max_angle_sum = numeric_limits<float>::lowest();
        int best_end = -1, best_prev = -1;

        for (const auto &[j, val] : dp[n - 1])
        {
            if (val > max_angle_sum)
            {
                max_angle_sum = val;
                best_end = n - 1;
                best_prev = j;
            }
        }

        if (best_end == -1)
        {
            // ROS_ERROR("折线化失败。");

            return ret;
        }

        // ROS_WARN("step2, max_angle_sum: %f", max_angle_sum);

        int current = best_end, prev_point = best_prev;

        while (current != -1)
        {
            path_polyline.push_back(path_initial[current]);
            int temp = prev[current][prev_point];
            current = prev_point;
            prev_point = temp;
        }

        reverse(path_polyline.begin(), path_polyline.end());
#else
        int current_index = 0;
        int prev_index = 0;
        vector<pair<float, float>> path_polyline_front;
        path_polyline_front.push_back(path_initial[0]);

        while (current_index < n - 1)
        {
#if POLYLINE_GEN_USE_BDDA
            float max_score = -INFINITY;
#endif

            int next_index = current_index + 1;

            for (int i = current_index + 1; i < n; i++)
            {
                float x1 = path_initial[current_index].first * resolu;
                float y1 = path_initial[current_index].second * resolu;
                float x2 = path_initial[i].first * resolu;
                float y2 = path_initial[i].second * resolu;

                if (!is_segment_no_collision(x1, y1, x2, y2, sampling_grid_dist, width, height, resolu, min_obs_dist, obs_dist_table))
                {
                    continue;
                }

#if POLYLINE_GEN_USE_BDDA
                float dist = hypot(x2 - x1, y2 - y1);

                if (dist > polyline_expected_dist)
                {
                    break;
                }

                float penalty = abs(dist - polyline_expected_dist);
                float penalty_val = dist_k * penalty;
                float score = -penalty_val;

                if (current_index != prev_index)
                {
                    float x0 = path_initial[prev_index].first * resolu;
                    float y0 = path_initial[prev_index].second * resolu;

                    float dx1 = x1 - x0;
                    float dy1 = y1 - y0;
                    float dx2 = x2 - x1;
                    float dy2 = y2 - y1;
                    float dot_product = dx1 * dx2 + dy1 * dy2;
                    float cross_product = dx1 * dy2 - dy1 * dx2;
                    float angle = abs(atan2(abs(cross_product), dot_product));

                    score += angle;
                }

                if (score > max_score)
                {
                    max_score = score;
                    next_index = i;
                }
#else
                next_index = i;
#endif
            }

            path_polyline_front.push_back(path_initial[next_index]);

            prev_index = current_index;
            current_index = next_index;
        }

        current_index = n - 1;
        prev_index = n - 1;
        vector<pair<float, float>> path_polyline_rear;
        path_polyline_rear.push_back(path_initial[n - 1]);

        while (current_index > 0)
        {
#if POLYLINE_GEN_USE_BDDA
            float max_score = -INFINITY;
#endif

            int next_index = current_index - 1;

            for (int i = current_index - 1; i >= 0; i--)
            {
                float x1 = path_initial[current_index].first * resolu;
                float y1 = path_initial[current_index].second * resolu;
                float x2 = path_initial[i].first * resolu;
                float y2 = path_initial[i].second * resolu;

                if (!is_segment_no_collision(x1, y1, x2, y2, sampling_grid_dist, width, height, resolu, min_obs_dist, obs_dist_table))
                {
                    continue;
                }

#if POLYLINE_GEN_USE_BDDA
                float dist = hypot(x2 - x1, y2 - y1);

                if (dist > polyline_expected_dist)
                {
                    break;
                }

                float penalty = abs(dist - polyline_expected_dist);
                float penalty_val = dist_k * penalty;
                float score = -penalty_val;

                if (current_index != prev_index)
                {
                    float x0 = path_initial[prev_index].first * resolu;
                    float y0 = path_initial[prev_index].second * resolu;

                    float dx1 = x1 - x0;
                    float dy1 = y1 - y0;
                    float dx2 = x2 - x1;
                    float dy2 = y2 - y1;
                    float dot_product = dx1 * dx2 + dy1 * dy2;
                    float cross_product = dx1 * dy2 - dy1 * dx2;
                    float angle = abs(atan2(abs(cross_product), dot_product));

                    score += angle;
                }

                if (score > max_score)
                {
                    max_score = score;
                    next_index = i;
                }
#else
                next_index = i;
#endif
            }

            path_polyline_rear.push_back(path_initial[next_index]);

            prev_index = current_index;
            current_index = next_index;
        }

        reverse(path_polyline_rear.begin(), path_polyline_rear.end());

#if POLYLINE_GEN_USE_BDDA
        float score_front = 0.0f, score_rear = 0.0f;

        for (int i = 0; i < path_polyline_front.size() - 1; i++)
        {
            float x1 = path_polyline_front[i].first * resolu;
            float y1 = path_polyline_front[i].second * resolu;
            float x2 = path_polyline_front[i + 1].first * resolu;
            float y2 = path_polyline_front[i + 1].second * resolu;

            float dist = hypot(x2 - x1, y2 - y1);

            float penalty = abs(dist - polyline_expected_dist);
            float penalty_val = dist_k * penalty;
            score_front -= penalty_val;

            if (i - 1 >= 0)
            {
                float x0 = path_polyline_front[prev_index].first * resolu;
                float y0 = path_polyline_front[prev_index].second * resolu;

                float dx1 = x1 - x0;
                float dy1 = y1 - y0;
                float dx2 = x2 - x1;
                float dy2 = y2 - y1;
                float dot_product = dx1 * dx2 + dy1 * dy2;
                float cross_product = dx1 * dy2 - dy1 * dx2;
                float angle = abs(atan2(abs(cross_product), dot_product));

                score_front += angle;
            }
        }

        for (int i = 0; i < path_polyline_rear.size() - 1; i++)
        {
            float x1 = path_polyline_rear[i].first * resolu;
            float y1 = path_polyline_rear[i].second * resolu;
            float x2 = path_polyline_rear[i + 1].first * resolu;
            float y2 = path_polyline_rear[i + 1].second * resolu;

            float dist = hypot(x2 - x1, y2 - y1);

            float penalty = abs(dist - polyline_expected_dist);
            float penalty_val = dist_k * penalty;
            score_rear -= penalty_val;

            if (i - 1 >= 0)
            {
                float x0 = path_polyline_rear[prev_index].first * resolu;
                float y0 = path_polyline_rear[prev_index].second * resolu;

                float dx1 = x1 - x0;
                float dy1 = y1 - y0;
                float dx2 = x2 - x1;
                float dy2 = y2 - y1;
                float dot_product = dx1 * dx2 + dy1 * dy2;
                float cross_product = dx1 * dy2 - dy1 * dx2;
                float angle = abs(atan2(abs(cross_product), dot_product));

                score_rear += angle;
            }
        }

        path_polyline = score_front > score_rear ? path_polyline_front : path_polyline_rear;
#else
        path_polyline = path_polyline_front.size() < path_polyline_rear.size() ? path_polyline_front : path_polyline_rear;
#endif
#endif

        // ROS_WARN("step3");
        vector<pair<float, float>> path_polyline_temp = path_polyline;
        path_polyline.clear();

        path_polyline.push_back(path_polyline_temp.front());

        for (size_t i = 1; i < path_polyline_temp.size(); i++)
        {
            float dx = (path_polyline_temp[i].first - path_polyline.back().first) * resolu;
            float dy = (path_polyline_temp[i].second - path_polyline.back().second) * resolu;
            float dist = std::sqrt(dx * dx + dy * dy);

            if (dist > 0.1)
            {
                path_polyline.push_back(path_polyline_temp[i]);
            }
        }

        // ROS_WARN("step4");

        vector<pair<float, float>> interpolated_points;
        const float interpolation_dist = 0.01 / resolu;

        for (size_t i = 0; i < path_polyline.size() - 1; i++)
        {
            float x0 = path_polyline[i].first;
            float y0 = path_polyline[i].second;
            float x1 = path_polyline[i + 1].first;
            float y1 = path_polyline[i + 1].second;

            float dx = x1 - x0;
            float dy = y1 - y0;
            float dist = hypot(dx, dy);
            int num_samples = max(1, static_cast<int>(ceil(dist / interpolation_dist)));

            for (int j = 0; j <= num_samples; j++)
            {
                float t = static_cast<float>(j) / num_samples;
                interpolated_points.emplace_back(x0 + t * dx, y0 + t * dy);
            }
        }

        // ROS_WARN("step5");

        ret = {true, interpolated_points, path_polyline};

        return ret;
    }
}