#include <utils/auto_mapping/tsp_optimization.h>

namespace tsp_optimization
{
    vector<geometry_msgs::Point32> tsp_solver::optimize(const geometry_msgs::Point32 &p_start,
                                                        const geometry_msgs::Point32 &p_goal,
                                                        const vector<geometry_msgs::Point32> &waypoints)
    {
        if (waypoints.empty())
        {
            return {p_goal};
        }

        if (waypoints.size() == 1)
        {
            return {waypoints[0], p_goal};
        }

        mt19937 generator(static_cast<unsigned int>(time(nullptr)));
        uniform_real_distribution<double> probability_distribution(0.0, 1.0);
        uniform_int_distribution<size_t> index_distribution(0, waypoints.size() - 1);

        vector<geometry_msgs::Point32> current_solution = waypoints;
        vector<geometry_msgs::Point32> best_solution = waypoints;

        double current_cost = calculate_distance(p_start, waypoints[0]);

        for (size_t i = 0; i < waypoints.size() - 1; i++)
        {
            current_cost += calculate_distance(waypoints[i], waypoints[i + 1]);
        }
        
        current_cost += calculate_distance(waypoints.back(), p_goal);

        double best_cost = current_cost;

        double temperature = 1000.0;
        double cooling_rate = 0.998;
        int max_iterations = 20000;

        for (int iteration = 0; iteration < max_iterations && temperature > 1e-3; ++iteration)
        {
            vector<geometry_msgs::Point32> neighbor = current_solution;

            size_t i = index_distribution(generator);
            size_t j = index_distribution(generator);

            while (i == j)
            {
                i = index_distribution(generator);
                j = index_distribution(generator);
            }

            swap(neighbor[i], neighbor[j]);

            double delta_cost = 0.0;

            if (i > 0)
            {
                delta_cost -= calculate_distance(current_solution[i - 1], current_solution[i]);
                delta_cost += calculate_distance(neighbor[i - 1], neighbor[i]);
            }

            if (i < current_solution.size() - 1)
            {
                delta_cost -= calculate_distance(current_solution[i], current_solution[i + 1]);
                delta_cost += calculate_distance(neighbor[i], neighbor[i + 1]);
            }

            if (j > 0 && j != i + 1)
            {
                delta_cost -= calculate_distance(current_solution[j - 1], current_solution[j]);
                delta_cost += calculate_distance(neighbor[j - 1], neighbor[j]);
            }

            if (j < current_solution.size() - 1 && j != i - 1)
            {
                delta_cost -= calculate_distance(current_solution[j], current_solution[j + 1]);
                delta_cost += calculate_distance(neighbor[j], neighbor[j + 1]);
            }

            if (i == 0)
            {
                delta_cost -= calculate_distance(p_start, current_solution[i]);
                delta_cost += calculate_distance(p_start, neighbor[i]);
            }
            else if (j == 0)
            {
                delta_cost -= calculate_distance(p_start, current_solution[j]);
                delta_cost += calculate_distance(p_start, neighbor[j]);
            }

            if (i == current_solution.size() - 1)
            {
                delta_cost -= calculate_distance(current_solution[i], p_goal);
                delta_cost += calculate_distance(neighbor[i], p_goal);
            }
            else if (j == current_solution.size() - 1)
            {
                delta_cost -= calculate_distance(current_solution[j], p_goal);
                delta_cost += calculate_distance(neighbor[j], p_goal);
            }

            double neighbor_cost = current_cost + delta_cost;

            if (delta_cost < -1e-6 || probability_distribution(generator) < exp(-delta_cost / temperature))
            {
                current_solution = neighbor;
                current_cost = neighbor_cost;

                if (current_cost < best_cost)
                {
                    best_cost = current_cost;
                    best_solution = current_solution;
                }
            }

            temperature *= cooling_rate;
        }

        best_solution.push_back(p_goal);

        return best_solution;
    }
}