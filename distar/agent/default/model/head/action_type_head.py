'''
Copyright 2020 Sensetime X-lab. All Rights Reserved

Main Function:
    1. Implementation for action_type_head, including basic processes.
'''
import torch
import torch.nn as nn
import torch.nn.functional as F
from distar.ctools.torch_utils import ResFCBlock, fc_block
from ..module_utils import build_activation
from ...lib.stat import ACTION_RACE_MASK
from typing import Optional, List, Tuple
from torch import Tensor



class ActionTypeHead(nn.Module):
    __constants__ = ['mask_action']
    def __init__(self, cfg):
        super(ActionTypeHead, self).__init__()
        self.whole_cfg = cfg
        self.cfg = self.whole_cfg.model.policy.head.action_type_head
        self.act = build_activation(self.cfg.activation)  # use relu as default
        self.project = fc_block(self.cfg.input_dim, self.cfg.res_dim, activation=self.act, norm_type=None)
        # self.project = fc_block(self.cfg.input_dim, self.cfg.res_dim)
        blocks = [ResFCBlock(self.cfg.res_dim, self.act, self.cfg.norm_type) for _ in
                  range(self.cfg.res_num)]
        self.res = nn.Sequential(*blocks)
        self.weight_norm = self.cfg.get('weight_norm', False)
        self.drop_Z = torch.nn.Dropout(p=self.cfg.get('drop_ratio', 0.0))
        self.drop_ratio = self.cfg.get('drop_ratio', 0.0)
        self.action_fc = build_activation('glu')(self.cfg.res_dim, self.cfg.action_num, self.cfg.context_dim)

        self.action_map_fc1 = fc_block(self.cfg.action_num, self.cfg.action_map_dim, activation=self.act,
                                      norm_type=None)
        self.action_map_fc2 = fc_block(self.cfg.action_map_dim, self.cfg.action_map_dim, activation=None,
                                      norm_type=None)
        self.glu1 = build_activation('glu')(self.cfg.action_map_dim, self.cfg.gate_dim, self.cfg.context_dim)
        self.glu2 = build_activation('glu')(self.cfg.input_dim, self.cfg.gate_dim, self.cfg.context_dim)
        self.action_num = self.cfg.action_num
        if self.whole_cfg.common.type == 'play':
            self.use_mask = True
            self.race = self.whole_cfg.env.races[0]
        else:
            self.use_mask = False
        # self.race = 'zerg'

        
        

    def forward(self, lstm_output, scalar_context, action_type: Optional[torch.Tensor] = None) -> Tuple[Tensor, Tensor, Tensor]:
        x = self.project(lstm_output)
        x = self.res(x)
        x = self.action_fc(x, scalar_context)
        x.div_(self.whole_cfg.model.temperature)
        if self.use_mask:
            mask = ACTION_RACE_MASK[self.race].to(x.device)
            x = x.masked_fill(~mask.unsqueeze(dim=0), -1e9)
        if action_type is None:
            p = F.softmax(x, dim=1)
            action_type = torch.multinomial(p, 1)[:, 0]

        action_one_hot = torch.nn.functional.one_hot(action_type.long(), self.action_num).float()  # one-hot version of action_type
        embedding1 = self.action_map_fc1(action_one_hot)
        embedding1 = self.action_map_fc2(embedding1)
        embedding1 = self.glu1(embedding1, scalar_context)
        embedding2 = self.glu2(lstm_output, scalar_context)
        embedding = embedding1 + embedding2

        return x, action_type, embedding
