import numpy as np
import pickle as pickle
from sandbox.rocky.tf.misc import tensor_utils
import copy


class MAMLVINEModelVecEnvExecutor(object):
    def __init__(self, env, model, max_path_length, n_parallel):
        self.env = env
        self.model = model
        self.init_obs = None

        self.unwrapped_env = env
        while hasattr(self.unwrapped_env, 'wrapped_env'):
            self.unwrapped_env = self.unwrapped_env.wrapped_env

        # make sure that enc has reward function
        assert hasattr(self.unwrapped_env, 'reward'), "env must have a reward function"

        # check whether env has done function
        self.has_done_fn = hasattr(self.unwrapped_env, 'done')

        self.n_parallel = n_parallel
        self._action_space = env.action_space
        self._observation_space = env.observation_space
        self.ts = np.zeros(n_parallel, dtype='int')
        self.max_path_length = max_path_length

    def step(self, action_n):
        """
        :param action_n: batches of actions for all models/taks stacked on top of each other (n_models * batch_per_model, ndim_act)
        :return: predicted observations (n_models * batch_per_model, ndim_obs)
        """

        assert action_n.shape[0] == self.n_parallel

        # use the model to make (predicted) steps
        prev_obs = self.current_obs

        action_batches_per_model = np.split(action_n, self.model.num_models)
        prev_obs_batches_per_model = np.split(prev_obs, self.model.num_models)
        next_obs_batches_per_model = []
        #todo: you don't need a for here
        for i, (prev_obs_batch, action_batch) in enumerate(zip(prev_obs_batches_per_model, action_batches_per_model)):
            next_obs_batch = self.model.predict(prev_obs_batch, action_batch, pred_type='all')[:,:,i]
            next_obs_batches_per_model.append(next_obs_batch)

        next_obs = np.concatenate(next_obs_batches_per_model, axis=0)
        rewards = self.unwrapped_env.reward(prev_obs, action_n, next_obs)

        if self.has_done_fn:
            dones = self.unwrapped_env.done(next_obs)
        else:
            dones = np.asarray([False for _ in range(self.n_parallel)])

        env_infos = [{} for _ in range(action_n.shape[0])]

        self.ts += 1
        if self.max_path_length is not None:
            dones[self.ts >= self.max_path_length] = True
        for (i, done) in enumerate(dones):
            if done:
                next_obs[i] = self.init_obs[i]
                self.ts[i] = 0

        self.current_obs = next_obs

        # transform obs to lists
        next_obs = [np.squeeze(o) for o in np.vsplit(next_obs, next_obs.shape[0])]
        return next_obs, list(rewards), list(dones), tensor_utils.stack_tensor_dict_list(env_infos) #lists

    def reset(self):
        results = [self.env.reset() for _ in range(self.n_parallel)] # get initial observation from environment
        self.current_obs = np.stack(results, axis=0)
        assert self.current_obs.ndim == 2
        self.ts[:] = 0
        return results

    @property
    def num_envs(self):
        return self.n_parallel

    @property
    def action_space(self):
        return self._action_space

    @property
    def observation_space(self):
        return self._observation_space

    def terminate(self):
        pass