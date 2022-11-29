#!/usr/bin/env python3

# Copyright (c) Facebook, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import abc
import math
import numpy as np
from numpy.lib import ufunclike
import os
import pickle
import random
import torch
import torch.nn as nn
import torch.nn.functional as F
from habitat_baselines.common.utils import CategoricalNet, Flatten, to_grid
from habitat_baselines.rl.models.projection import Projection, RotateTensor, get_grid
from habitat_baselines.rl.models.rnn_state_encoder import RNNStateEncoder
from habitat_baselines.rl.models.simple_cnn import RGBCNNNonOracle, RGBCNNOracle, MapCNN
from habitat_baselines.rl.ppo.aux_losses_utils import (
    get_obj_poses,
    compute_distance_labels,
    compute_direction_labels,
)


class PolicyNonOracle(nn.Module):
    def __init__(self, net, dim_actions):
        super().__init__()
        self.net = net
        self.dim_actions = dim_actions

        self.action_distribution = CategoricalNet(
            self.net.output_size, self.dim_actions
        )
        self.critic = CriticHead(self.net.output_size)

    def forward(self, *x):
        raise NotImplementedError

    def act(
        self,
        observations,
        rnn_hidden_states,
        global_map,
        prev_actions,
        masks,
        deterministic=False,
        nb_steps=None,
        current_episodes=None,
    ):
        features, rnn_hidden_states, global_map = self.net(
            observations,
            rnn_hidden_states,
            global_map,
            prev_actions,
            masks,
            nb_steps,
            current_episodes,
        )

        distribution = self.action_distribution(features)
        value = self.critic(features)

        if deterministic:
            action = distribution.mode()
        else:
            action = distribution.sample()

        action_log_probs = distribution.log_probs(action)

        return value, action, action_log_probs, rnn_hidden_states, global_map

    def get_value(
        self, observations, rnn_hidden_states, global_map, prev_actions, masks
    ):
        features, _, _ = self.net(
            observations, rnn_hidden_states, global_map, prev_actions, masks
        )
        return self.critic(features)

    def evaluate_actions(
        self, observations, rnn_hidden_states, global_map, prev_actions, masks, action
    ):
        (
            features,
            rnn_hidden_states,
            global_map,
            loss_seen,
            loss_directions,
            loss_distances,
            pred_seen,
            seen_labels,
        ) = self.net(
            observations,
            rnn_hidden_states,
            global_map,
            prev_actions,
            masks,
            ev=1,
            aux_loss=True,
        )

        distribution = self.action_distribution(features)
        value = self.critic(features)

        action_log_probs = distribution.log_probs(action)
        distribution_entropy = distribution.entropy().mean()

        return (
            value,
            action_log_probs,
            distribution_entropy,
            rnn_hidden_states,
            loss_seen,
            loss_directions,
            loss_distances,
            pred_seen,
            seen_labels,
        )


class PolicyOracle(nn.Module):
    def __init__(self, net, dim_actions):
        super().__init__()
        self.net = net
        self.dim_actions = dim_actions

        self.action_distribution = CategoricalNet(
            self.net.output_size, self.dim_actions
        )
        self.critic = CriticHead(self.net.output_size)

    def forward(self, *x):
        raise NotImplementedError

    def act(
        self,
        observations,
        rnn_hidden_states,
        prev_actions,
        masks,
        deterministic=False,
    ):
        features, rnn_hidden_states, *_ = self.net(
            observations, rnn_hidden_states, prev_actions, masks
        )

        distribution = self.action_distribution(features)
        value = self.critic(features)

        if deterministic:
            action = distribution.mode()
        else:
            action = distribution.sample()

        action_log_probs = distribution.log_probs(action)

        return value, action, action_log_probs, rnn_hidden_states

    def get_value(self, observations, rnn_hidden_states, prev_actions, masks):
        features, *_ = self.net(observations, rnn_hidden_states, prev_actions, masks)
        return self.critic(features)

    def evaluate_actions(
        self, observations, rnn_hidden_states, prev_actions, masks, action
    ):
        (
            features,
            rnn_hidden_states,
            loss_seen,
            loss_directions,
            loss_distances,
            pred_seen,
            seen_labels,
        ) = self.net(observations, rnn_hidden_states, prev_actions, masks, True)

        distribution = self.action_distribution(features)
        value = self.critic(features)

        action_log_probs = distribution.log_probs(action)
        distribution_entropy = distribution.entropy().mean()

        return (
            value,
            action_log_probs,
            distribution_entropy,
            rnn_hidden_states,
            loss_seen,
            loss_directions,
            loss_distances,
            pred_seen,
            seen_labels,
        )


class CriticHead(nn.Module):
    def __init__(self, input_size):
        super().__init__()
        self.fc = nn.Linear(input_size, 1)
        nn.init.orthogonal_(self.fc.weight)
        nn.init.constant_(self.fc.bias, 0)

    def forward(self, x):
        return self.fc(x)


class BaselinePolicyNonOracle(PolicyNonOracle):
    def __init__(
        self,
        batch_size,
        observation_space,
        action_space,
        goal_sensor_uuid,
        device,
        object_category_embedding_size,
        previous_action_embedding_size,
        use_previous_action,
        egocentric_map_size,
        global_map_size,
        global_map_depth,
        coordinate_min,
        coordinate_max,
        aux_loss_seen_coef,
        aux_loss_direction_coef,
        aux_loss_distance_coef,
        hidden_size=512,
    ):
        super().__init__(
            BaselineNetNonOracle(
                batch_size,
                observation_space=observation_space,
                hidden_size=hidden_size,
                goal_sensor_uuid=goal_sensor_uuid,
                device=device,
                object_category_embedding_size=object_category_embedding_size,
                previous_action_embedding_size=previous_action_embedding_size,
                use_previous_action=use_previous_action,
                egocentric_map_size=egocentric_map_size,
                global_map_size=global_map_size,
                global_map_depth=global_map_depth,
                coordinate_min=coordinate_min,
                coordinate_max=coordinate_max,
                aux_loss_seen_coef=aux_loss_seen_coef,
                aux_loss_direction_coef=aux_loss_direction_coef,
                aux_loss_distance_coef=aux_loss_distance_coef,
            ),
            action_space.n,
        )


class BaselinePolicyOracle(PolicyOracle):
    def __init__(
        self,
        agent_type,
        observation_space,
        action_space,
        goal_sensor_uuid,
        device,
        object_category_embedding_size,
        previous_action_embedding_size,
        use_previous_action,
        aux_loss_seen_coef,
        aux_loss_direction_coef,
        aux_loss_distance_coef,
        hidden_size=512,
    ):
        super().__init__(
            BaselineNetOracle(
                agent_type,
                observation_space=observation_space,
                hidden_size=hidden_size,
                goal_sensor_uuid=goal_sensor_uuid,
                device=device,
                object_category_embedding_size=object_category_embedding_size,
                previous_action_embedding_size=previous_action_embedding_size,
                use_previous_action=use_previous_action,
                aux_loss_seen_coef=aux_loss_seen_coef,
                aux_loss_direction_coef=aux_loss_direction_coef,
                aux_loss_distance_coef=aux_loss_distance_coef,
            ),
            action_space.n,
        )


class Net(nn.Module, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def forward(self, observations, rnn_hidden_states, global_map, prev_actions):
        pass

    @property
    @abc.abstractmethod
    def output_size(self):
        pass

    @property
    @abc.abstractmethod
    def num_recurrent_layers(self):
        pass

    @property
    @abc.abstractmethod
    def is_blind(self):
        pass


class BaselineNetNonOracle(Net):
    r"""Network which passes the input image through CNN and concatenates
    goal vector with CNN's output and passes that through RNN.
    """

    def __init__(
        self,
        batch_size,
        observation_space,
        hidden_size,
        goal_sensor_uuid,
        device,
        object_category_embedding_size,
        previous_action_embedding_size,
        use_previous_action,
        egocentric_map_size,
        global_map_size,
        global_map_depth,
        coordinate_min,
        coordinate_max,
        aux_loss_seen_coef,
        aux_loss_direction_coef,
        aux_loss_distance_coef,
    ):
        super().__init__()
        self.goal_sensor_uuid = goal_sensor_uuid
        self._n_input_goal = observation_space.spaces[self.goal_sensor_uuid].shape[0]
        self._hidden_size = hidden_size
        self.device = device
        self.use_previous_action = use_previous_action
        self.egocentric_map_size = egocentric_map_size
        self.global_map_size = global_map_size
        self.global_map_depth = global_map_depth

        self.visual_encoder = RGBCNNNonOracle(observation_space, hidden_size)
        self.map_encoder = MapCNN(51, 256, "non-oracle")

        self.projection = Projection(
            egocentric_map_size, global_map_size, device, coordinate_min, coordinate_max
        )

        self.to_grid = to_grid(global_map_size, coordinate_min, coordinate_max)
        self.rotate_tensor = RotateTensor(device)

        self.image_features_linear = nn.Linear(32 * 28 * 28, 512)

        self.flatten = Flatten()

        if self.use_previous_action:
            self.state_encoder = RNNStateEncoder(
                self._hidden_size
                + 256
                + object_category_embedding_size
                + previous_action_embedding_size,
                self._hidden_size,
            )
        else:
            self.state_encoder = RNNStateEncoder(
                (0 if self.is_blind else self._hidden_size)
                + object_category_embedding_size,
                self._hidden_size,  # Replace 2 by number of target categories later
            )
        self.goal_embedding = nn.Embedding(8, object_category_embedding_size)
        self.action_embedding = nn.Embedding(4, previous_action_embedding_size)
        self.full_global_map = torch.zeros(
            batch_size,
            global_map_size,
            global_map_size,
            global_map_depth,
            device=self.device,
        )

        # Auxiliary losses
        if aux_loss_seen_coef is not None:
            self.fc_seen = nn.Linear(self._hidden_size, 2)
            nn.init.orthogonal_(self.fc_seen.weight)
            nn.init.constant_(self.fc_seen.bias, 0)
        else:
            self.fc_seen = None

        if aux_loss_direction_coef is not None:
            self.fc_direction = nn.Linear(self._hidden_size, 12)
            nn.init.orthogonal_(self.fc_direction.weight)
            nn.init.constant_(self.fc_direction.bias, 0)
        else:
            self.fc_direction = None

        if aux_loss_distance_coef is not None:
            self.fc_distance = nn.Linear(self._hidden_size, 35)
            nn.init.orthogonal_(self.fc_distance.weight)
            nn.init.constant_(self.fc_distance.bias, 0)
        else:
            self.fc_distance = None

        self.train()

    @property
    def output_size(self):
        return self._hidden_size

    @property
    def is_blind(self):
        return self.visual_encoder.is_blind

    @property
    def num_recurrent_layers(self):
        return self.state_encoder.num_recurrent_layers

    def get_target_encoding(self, observations):
        return observations[self.goal_sensor_uuid]

    def forward(
        self,
        observations,
        rnn_hidden_states,
        global_map,
        prev_actions,
        masks,
        nb_steps=None,
        current_episodes=None,
        ev=0,
        aux_loss=False,
    ):
        target_encoding = self.get_target_encoding(observations)
        goal_embed = self.goal_embedding(
            (target_encoding).type(torch.LongTensor).to(self.device)
        ).squeeze(1)

        loss_seen = None
        pred_softmax = None
        loss_directions = None
        loss_distances = None
        seen_labels = None

        if aux_loss and (
            (self.fc_seen is not None)
            or (self.fc_direction is not None)
            or (self.fc_distance is not None)
        ):
            # Get positions of target objs
            mean_i_obj, mean_j_obj, gt_seen, not_visible_goals = get_obj_poses(
                observations
            )

            # Compute euclidian distance
            if self.fc_distance is not None:
                distance_labels = compute_distance_labels(
                    mean_i_obj, mean_j_obj, not_visible_goals, self.device
                )

            if self.fc_seen is not None:
                seen_labels = np.array(gt_seen).astype(np.int_)
                seen_labels = torch.from_numpy(seen_labels).to(self.device)

            # Compute directions
            if self.fc_direction is not None:
                direction_labels = compute_direction_labels(
                    mean_i_obj, mean_j_obj, not_visible_goals, self.device
                )

        if not self.is_blind:
            perception_embed = self.visual_encoder(observations)
        projection = self.projection.forward(
            perception_embed, observations["depth"] * 10, -(observations["compass"])
        )
        perception_embed = self.image_features_linear(self.flatten(perception_embed))
        grid_x, grid_y = self.to_grid.get_grid_coords(observations["gps"])
        bs = global_map.shape[0]
        ##forward pass specific
        if ev == 0:
            self.full_global_map[:bs, :, :, :] = self.full_global_map[
                :bs, :, :, :
            ] * masks.unsqueeze(1).unsqueeze(1)
            if bs != 18:
                self.full_global_map[bs:, :, :, :] = (
                    self.full_global_map[bs:, :, :, :] * 0
                )
            if torch.cuda.is_available():
                with torch.cuda.device(0):
                    agent_view = torch.cuda.FloatTensor(
                        bs,
                        self.global_map_depth,
                        self.global_map_size,
                        self.global_map_size,
                    ).fill_(0)
            else:
                agent_view = (
                    torch.FloatTensor(
                        bs,
                        self.global_map_depth,
                        self.global_map_size,
                        self.global_map_size,
                    )
                    .to(self.device)
                    .fill_(0)
                )
            agent_view[
                :,
                :,
                self.global_map_size // 2
                - math.floor(self.egocentric_map_size / 2) : self.global_map_size // 2
                + math.ceil(self.egocentric_map_size / 2),
                self.global_map_size // 2
                - math.floor(self.egocentric_map_size / 2) : self.global_map_size // 2
                + math.ceil(self.egocentric_map_size / 2),
            ] = projection
            st_pose = torch.cat(
                [
                    -(grid_y.unsqueeze(1) - (self.global_map_size // 2))
                    / (self.global_map_size // 2),
                    -(grid_x.unsqueeze(1) - (self.global_map_size // 2))
                    / (self.global_map_size // 2),
                    observations["compass"],
                ],
                dim=1,
            )

            rot_mat, trans_mat = get_grid(st_pose, agent_view.size(), self.device)
            rotated = F.grid_sample(agent_view, rot_mat)
            translated = F.grid_sample(rotated, trans_mat)

            self.full_global_map[:bs, :, :, :] = torch.max(
                self.full_global_map[:bs, :, :, :], translated.permute(0, 2, 3, 1)
            )
            st_pose_retrieval = torch.cat(
                [
                    (grid_y.unsqueeze(1) - (self.global_map_size // 2))
                    / (self.global_map_size // 2),
                    (grid_x.unsqueeze(1) - (self.global_map_size // 2))
                    / (self.global_map_size // 2),
                    torch.zeros_like(observations["compass"]),
                ],
                dim=1,
            )
            _, trans_mat_retrieval = get_grid(
                st_pose_retrieval, agent_view.size(), self.device
            )
            translated_retrieval = F.grid_sample(
                self.full_global_map[:bs, :, :, :].permute(0, 3, 1, 2),
                trans_mat_retrieval,
            )
            translated_retrieval = translated_retrieval[
                :,
                :,
                self.global_map_size // 2
                - math.floor(51 / 2) : self.global_map_size // 2
                + math.ceil(51 / 2),
                self.global_map_size // 2
                - math.floor(51 / 2) : self.global_map_size // 2
                + math.ceil(51 / 2),
            ]
            final_retrieval = self.rotate_tensor.forward(
                translated_retrieval, observations["compass"]
            )

            global_map_embed = self.map_encoder(final_retrieval.permute(0, 2, 3, 1))

            if self.use_previous_action:
                action_embedding = self.action_embedding(prev_actions).squeeze(1)

            x = torch.cat(
                (perception_embed, global_map_embed, goal_embed, action_embedding),
                dim=1,
            )
            x, rnn_hidden_states = self.state_encoder(x, rnn_hidden_states, masks)

            return x, rnn_hidden_states, final_retrieval.permute(0, 2, 3, 1)
        else:

            global_map = global_map * masks.unsqueeze(1).unsqueeze(1)
            with torch.cuda.device(0):
                agent_view = torch.cuda.FloatTensor(
                    bs, self.global_map_depth, 51, 51
                ).fill_(0)
            agent_view[
                :,
                :,
                51 // 2
                - math.floor(self.egocentric_map_size / 2) : 51 // 2
                + math.ceil(self.egocentric_map_size / 2),
                51 // 2
                - math.floor(self.egocentric_map_size / 2) : 51 // 2
                + math.ceil(self.egocentric_map_size / 2),
            ] = projection

            final_retrieval = torch.max(global_map, agent_view.permute(0, 2, 3, 1))

            global_map_embed = self.map_encoder(final_retrieval)

            if self.use_previous_action:
                action_embedding = self.action_embedding(prev_actions).squeeze(1)

            x = torch.cat(
                (perception_embed, global_map_embed, goal_embed, action_embedding),
                dim=1,
            )
            x, rnn_hidden_states = self.state_encoder(x, rnn_hidden_states, masks)

            # Compute auxiliary losses
            if aux_loss and (
                (self.fc_seen is not None)
                or (self.fc_direction is not None)
                or (self.fc_distance is not None)
            ):
                if self.fc_seen is not None:
                    pred_seen = self.fc_seen(x)
                    loss_seen = F.cross_entropy(pred_seen, seen_labels)
                    pred_softmax = F.softmax(pred_seen, dim=1)

                indices_to_keep = (seen_labels == 1).nonzero()[:, 0]
                if len(indices_to_keep) > 0:
                    if self.fc_direction is not None:
                        pred_directions = self.fc_direction(x)
                        loss_directions = F.cross_entropy(
                            pred_directions[indices_to_keep],
                            direction_labels[indices_to_keep],
                        )

                    if self.fc_distance is not None:
                        pred_distances = self.fc_distance(x)
                        loss_distances = F.cross_entropy(
                            pred_distances[indices_to_keep],
                            distance_labels[indices_to_keep],
                        )
                else:
                    if self.fc_direction is not None:
                        loss_directions = torch.zeros(1).squeeze(0).to(self.device)
                    if self.fc_distance is not None:
                        loss_distances = torch.zeros(1).squeeze(0).to(self.device)

            return (
                x,
                rnn_hidden_states,
                final_retrieval.permute(0, 2, 3, 1),
                loss_seen,
                loss_directions,
                loss_distances,
                pred_softmax,
                seen_labels,
            )


class BaselineNetOracle(Net):
    r"""Network which passes the input image through CNN and concatenates
    goal vector with CNN's output and passes that through RNN.
    """

    def __init__(
        self,
        agent_type,
        observation_space,
        hidden_size,
        goal_sensor_uuid,
        device,
        object_category_embedding_size,
        previous_action_embedding_size,
        use_previous_action,
        aux_loss_seen_coef,
        aux_loss_direction_coef,
        aux_loss_distance_coef,
    ):
        super().__init__()
        self.agent_type = agent_type
        self.goal_sensor_uuid = goal_sensor_uuid
        self._n_input_goal = observation_space.spaces[self.goal_sensor_uuid].shape[0]
        self._hidden_size = hidden_size
        self.device = device
        self.use_previous_action = use_previous_action

        self.visual_encoder = RGBCNNOracle(observation_space, 512)
        if agent_type == "oracle":
            self.map_encoder = MapCNN(50, 256, agent_type)
            self.occupancy_embedding = nn.Embedding(3, 16)
            self.object_embedding = nn.Embedding(9, 16)
            self.goal_embedding = nn.Embedding(9, object_category_embedding_size)

        elif agent_type == "no-map":
            self.goal_embedding = nn.Embedding(8, object_category_embedding_size)
        elif agent_type == "oracle-ego":
            self.map_encoder = MapCNN(50, 256, agent_type)
            self.object_embedding = nn.Embedding(10, 16)
            self.goal_embedding = nn.Embedding(9, object_category_embedding_size)

        self.action_embedding = nn.Embedding(4, previous_action_embedding_size)

        if self.use_previous_action:
            self.state_encoder = RNNStateEncoder(
                (self._hidden_size)
                + object_category_embedding_size
                + previous_action_embedding_size,
                self._hidden_size,
            )
        else:
            self.state_encoder = RNNStateEncoder(
                (self._hidden_size) + object_category_embedding_size,
                self._hidden_size,
            )

        # Auxiliary losses
        if aux_loss_seen_coef is not None:
            self.fc_seen = nn.Linear(self._hidden_size, 2)
            nn.init.orthogonal_(self.fc_seen.weight)
            nn.init.constant_(self.fc_seen.bias, 0)
        else:
            self.fc_seen = None

        if aux_loss_direction_coef is not None:
            self.fc_direction = nn.Linear(self._hidden_size, 12)
            nn.init.orthogonal_(self.fc_direction.weight)
            nn.init.constant_(self.fc_direction.bias, 0)
        else:
            self.fc_direction = None

        if aux_loss_distance_coef is not None:
            self.fc_distance = nn.Linear(self._hidden_size, 35)
            nn.init.orthogonal_(self.fc_distance.weight)
            nn.init.constant_(self.fc_distance.bias, 0)
        else:
            self.fc_distance = None

        self.train()

    @property
    def output_size(self):
        return self._hidden_size

    @property
    def is_blind(self):
        return self.visual_encoder.is_blind

    @property
    def num_recurrent_layers(self):
        return self.state_encoder.num_recurrent_layers

    def get_target_encoding(self, observations):
        return observations[self.goal_sensor_uuid]

    def forward(
        self, observations, rnn_hidden_states, prev_actions, masks, aux_loss=False
    ):
        target_encoding = self.get_target_encoding(observations)
        x = [
            self.goal_embedding(
                (target_encoding).type(torch.LongTensor).to(self.device)
            ).squeeze(1)
        ]
        bs = target_encoding.shape[0]
        if not self.is_blind:
            perception_embed = self.visual_encoder(observations)
            x = [perception_embed] + x

        loss_seen = None
        pred_softmax = None
        loss_directions = None
        loss_distances = None
        seen_labels = None

        if aux_loss and (
            (self.fc_seen is not None)
            or (self.fc_direction is not None)
            or (self.fc_distance is not None)
        ):
            # Get positions of target objs
            mean_i_obj, mean_j_obj, gt_seen, not_visible_goals = get_obj_poses(
                observations
            )

            # Compute euclidian distance
            if self.fc_distance is not None:
                distance_labels = compute_distance_labels(
                    mean_i_obj, mean_j_obj, not_visible_goals, self.device
                )

            if self.fc_seen is not None:
                seen_labels = np.array(gt_seen).astype(np.int_)
                seen_labels = torch.from_numpy(seen_labels).to(self.device)

            # Compute directions
            if self.fc_direction is not None:
                direction_labels = compute_direction_labels(
                    mean_i_obj, mean_j_obj, not_visible_goals, self.device
                )

        if self.agent_type != "no-map":
            global_map_embedding = []
            global_map = observations["semMap"]
            if self.agent_type == "oracle":
                global_map_embedding.append(
                    self.occupancy_embedding(
                        global_map[:, :, :, 0]
                        .type(torch.LongTensor)
                        .to(self.device)
                        .view(-1)
                    ).view(bs, 50, 50, -1)
                )

            global_map_embedding.append(
                self.object_embedding(
                    global_map[:, :, :, 1]
                    .type(torch.LongTensor)
                    .to(self.device)
                    .view(-1)
                ).view(bs, 50, 50, -1)
            )
            global_map_embedding = torch.cat(global_map_embedding, dim=3)
            map_embed = self.map_encoder(global_map_embedding)
            x = [map_embed] + x

        if self.use_previous_action:
            x = torch.cat(x + [self.action_embedding(prev_actions).squeeze(1)], dim=1)
        else:
            x = torch.cat(x, dim=1)
        x, rnn_hidden_states = self.state_encoder(x, rnn_hidden_states, masks)

        # Compute auxiliary losses
        if aux_loss and (
            (self.fc_seen is not None)
            or (self.fc_direction is not None)
            or (self.fc_distance is not None)
        ):
            if self.fc_seen is not None:
                pred_seen = self.fc_seen(x)
                loss_seen = F.cross_entropy(pred_seen, seen_labels)
                pred_softmax = F.softmax(pred_seen, dim=1)

            indices_to_keep = (seen_labels == 1).nonzero()[:, 0]
            if len(indices_to_keep) > 0:
                if self.fc_direction is not None:
                    pred_directions = self.fc_direction(x)
                    loss_directions = F.cross_entropy(
                        pred_directions[indices_to_keep],
                        direction_labels[indices_to_keep],
                    )

                if self.fc_distance is not None:
                    pred_distances = self.fc_distance(x)
                    loss_distances = F.cross_entropy(
                        pred_distances[indices_to_keep],
                        distance_labels[indices_to_keep],
                    )
            else:
                if self.fc_direction is not None:
                    loss_directions = torch.zeros(1).squeeze(0).to(self.device)
                if self.fc_distance is not None:
                    loss_distances = torch.zeros(1).squeeze(0).to(self.device)

        return (
            x,
            rnn_hidden_states,
            loss_seen,
            loss_directions,
            loss_distances,
            pred_softmax,
            seen_labels,
        )
