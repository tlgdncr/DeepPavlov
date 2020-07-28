# Copyright 2017 Neural Networks and Deep Learning lab, MIPT
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from logging import getLogger
from typing import List, Dict, Union

import numpy as np
import torch
from transformers.data.processors.utils import InputFeatures

from deeppavlov.core.common.registry import register
from deeppavlov.models.torch_bert.torch_bert_classifier import TorchBertClassifierModel

logger = getLogger(__name__)


@register('torch_bert_ranker')
class TorchBertRankerModel(TorchBertClassifierModel):
    """BERT-based model for interaction-based text ranking on PyTorch.

    Linear transformation is trained over the BERT pooled output from [CLS] token.
    Predicted probabilities of classes are used as a similarity measure for ranking.

    Args:
        bert_config_file: path to Bert configuration file
        n_classes: number of classes
        keep_prob: dropout keep_prob for non-Bert layers
        return_probas: set True if class probabilities are returned instead of the most probable label
    """

    def __init__(self, pretrained_bert=None, bert_config_file=None,
                 n_classes=2, keep_prob=0.9, return_probas=True,
                 optimizer="AdamW",
                 optimizer_parameters={"lr": 2e-5, "weight_decay": 0.01, "betas": (0.9, 0.999), "eps": 1e-6},
                 **kwargs) -> None:
        super().__init__(pretrained_bert=pretrained_bert, bert_config_file=bert_config_file,
                         n_classes=n_classes, keep_prob=keep_prob, return_probas=return_probas,
                         optimizer=optimizer, optimizer_parameters=optimizer_parameters,
                         **kwargs)

    def train_on_batch(self, features_li: List[List[InputFeatures]], y: Union[List[int], List[List[int]]]) -> Dict:
        """Train the model on the given batch.

        Args:
            features_li: list with the single element containing the batch of InputFeatures
            y: batch of labels (class id or one-hot encoding)

        Returns:
            dict with loss and learning rate values
        """
        features = features_li[0]

        input_ids = [f.input_ids for f in features]
        input_masks = [f.attention_mask for f in features]

        b_input_ids = torch.cat(input_ids, dim=0).to(self.device)
        b_input_masks = torch.cat(input_masks, dim=0).to(self.device)
        b_labels = torch.from_numpy(np.array(y)).to(self.device)

        self.optimizer.zero_grad()

        loss, logits = self.model(b_input_ids, token_type_ids=None, attention_mask=b_input_masks,
                                  labels=b_labels)
        loss.backward()
        # Clip the norm of the gradients to 1.0.
        # This is to help prevent the "exploding gradients" problem.
        # torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)

        self.optimizer.step()
        if self.lr_scheduler is not None:
            self.lr_scheduler.step()

        return {'loss': loss.item()}

    def __call__(self, features_li: List[List[InputFeatures]]) -> Union[List[int], List[List[float]]]:
        """Calculate scores for the given context over candidate responses.

        Args:
            features_li: list of elements where each element contains the batch of features
             for contexts with particular response candidates

        Returns:
            predicted scores for contexts over response candidates
        """
        if len(features_li) == 1 and len(features_li[0]) == 1:
            msg = "It is not intended to use the {} in the interact mode.".format(self.__class__)
            logger.error(msg)
            return [msg]

        predictions = []
        for features in features_li:

            input_ids = [f.input_ids for f in features]
            input_masks = [f.attention_mask for f in features]

            b_input_ids = torch.cat(input_ids, dim=0).to(self.device)
            b_input_masks = torch.cat(input_masks, dim=0).to(self.device)

            with torch.no_grad():
                # Forward pass, calculate logit predictions
                logits = self.model(b_input_ids, token_type_ids=None, attention_mask=b_input_masks)

            # Move logits and labels to CPU and to numpy arrays
            logits = logits[0].detach().cpu().numpy()

            if self.return_probas:
                pred = logits[:, 1]
            else:
                pred = np.argmax(logits, axis=1)
            predictions.append(pred)

        if len(features_li) == 1:
            predictions = predictions[0]
        else:
            predictions = np.hstack([np.expand_dims(el, 1) for el in predictions])

        return predictions
