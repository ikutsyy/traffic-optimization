import GPy
import numpy as np
from emukit.model_wrappers.gpy_model_wrappers import GPyModelWrapper
from emukit.experimental_design.acquisitions import ModelVariance
from emukit.core.optimization import GradientAcquisitionOptimizer
from emukit.examples.gp_bayesian_optimization.single_objective_bayesian_optimization import GPBayesianOptimization
from emukit.core import ParameterSpace, ContinuousParameter, DiscreteParameter
from runner import call_sim

class emu():
    def __init__(self, iterations):
        X = np.array([[1, 1, 1, 1, 0, 0.01, 2, 2, 2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]])
        Y = np.array([[call_sim(X[0])]])

        # Define parameter space for the simulator variables
        space = ParameterSpace([ContinuousParameter('traffic_light_1', 1, 100),
                                ContinuousParameter('traffic_light_2', 1, 100),
                                ContinuousParameter('traffic_light_3', 1, 100),
                                ContinuousParameter('traffic_light_4', 1, 100),
                                ContinuousParameter('sigma', 0, 1),
                                ContinuousParameter('tau', 0.01, 1000), # Don't know how to do no upper bound
                                ContinuousParameter('trucks', 0, 100),
                                ContinuousParameter('cars', 0, 100),
                                ContinuousParameter('bikes', 0, 100),
                                ContinuousParameter('NE', 0, 0.5),
                                ContinuousParameter('NS', 0, 0.5),
                                ContinuousParameter('NW', 0, 0.5),
                                ContinuousParameter('EN', 0, 0.5),
                                ContinuousParameter('ES', 0, 0.5),
                                ContinuousParameter('EW', 0, 0.5),
                                ContinuousParameter('SN', 0, 0.5),
                                ContinuousParameter('SE', 0, 0.5),
                                ContinuousParameter('SW', 0, 0.5),
                                ContinuousParameter('WN', 0, 0.5),
                                ContinuousParameter('WE', 0, 0.5),
                                ContinuousParameter('WS', 0, 0.5),
                                ])

        # Kernel
        kern = GPy.kern.RBF(21, lengthscale=0.08, variance=20)
        # GP
        gpy_model = GPy.models.GPRegression(X, Y, kern, noise_var=1e-10)
        # Emukit Model
        emukit_model = GPyModelWrapper(gpy_model)

        ################################################################################
        # OPTION 1: Manual
        ################################################################################

        # Acquisition function
        us_acquisition = ModelVariance(emukit_model)
        # Acquisition optimiser
        optimizer = GradientAcquisitionOptimizer(space)

        for _ in range(iterations):
            # Get next point
            x_new, _ = optimizer.optimize(us_acquisition)

            # Run simulator on new
            y_new = np.array([call_sim(list(x_new[0]), early_stop=True)])


            X = np.append(X, x_new, axis=0)
            Y = np.append(Y, np.expand_dims(y_new, 0), axis=0)
            print(f"X: {X}")
            print(f"Y: {Y}")

            # Add data to model
            emukit_model.set_data(np.array(X), np.array(Y))

        self.model = emukit_model

        ################################################################################
        # OPTION 2: Easy
        ################################################################################

        # Basically zero documentation :(
        #from emukit.experimental_design.experimental_design_loop import ExperimentalDesignLoop
        #ed = ExperimentalDesignLoop(space=space,
        #                            model=emukit_model,
        #                            acquisition = ModelVariance(emukit_model),
        #                            acquisition_optimizer = GradientAcquisitionOptimizer(space)
        #                            )
        #ed.run_loop(target_function, 10)

        #self.model = ed.model

    def call(self, x):
        # Returns tuple of mean and variance
        return self.model.predict(x)

    # partial_x will be things like number of cars on the road
    def optimise(self, partial_x):

        # optimise_x are the parameters to optimise such as speed limit
        def partial_call(optimise_x):
            return self.call(partial_x+optimise_x)[0]

        optimise_x = [ContinuousParameter('traffic_light_1', 1, 100),
                      ContinuousParameter('traffic_light_2', 1, 100),
                      ContinuousParameter('traffic_light_3', 1, 100),
                      ContinuousParameter('traffic_light_4', 1, 100)]
        bo = GPBayesianOptimization(variables_list=optimise_x,
                            X=X_init, Y=Y_init)
        bo.run_optimization(partial_call, 10)

        maximum = bo.loop_state.X[np.argmax(bo.loop_state.Y)]
        return maximum

emu(10)
