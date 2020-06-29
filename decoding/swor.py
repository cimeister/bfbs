import numpy as np
import time
import copy
import logging
from collections import defaultdict

import utils
from decoding.core import Decoder, PartialHypothesis


class BasicSworDecoder(Decoder):
    def __init__(self, decoder_args):
        """Creates a new SWOR decoder instance. The following values are
        fetched from `decoder_args`:
        
            nbest (int): number of desired samples. 
            temperature (float): temperature for shifting probability distributions
        
        Args:
            decoder_args (object): Decoder configuration passed through
                                   from the configuration API.
        """
        super(BasicSworDecoder, self).__init__(decoder_args)
        self.nbest = decoder_args.nbest
        self.early_stopping = decoder_args.early_stopping
        assert not self.gumbel
        
    def decode(self, src_sentence):
        self.initialize_predictors(src_sentence)
        self.covered_lprob = utils.NEG_INF

        while len(self.full_hypos) < self.nbest and self.samples_left():
            if np.exp(self.covered_lprob) >= 1.0 - utils.MACHINE_EPS:
                logging.warn("Samples cover 100% of probability. Behavior beyond this point is undefined")
            self.reset_predictors(src_sentence)
            hypo = PartialHypothesis(self.get_predictor_states())
            hypo, score = self._expand_hypo(hypo, seed=len(self.full_hypos))
            self.add_full_hypo(hypo.generate_full_hypothesis())
            self.covered_lprob = utils.log_add(self.covered_lprob, score)
            
        logging.info("%d sentences covering %f probability" %(len(self.full_hypos), np.exp(self.covered_lprob)))
        return self.full_hypos

    def initialize_predictors(self, src_sentence):
        self.dists = MapDist()
        super().initialize_predictors(src_sentence)

    def _expand_hypo(self, hypo, seed=0):
        if hypo.get_last_word() == utils.EOS_ID or len(hypo) == self.max_len:
            return hypo, 0.0

        prefix = tuple(hypo.trgt_sentence)
        if prefix in self.dists:
            ids, lprobabilities, adjusted_lprobabilities, states = self.dists.get(prefix)
            hypo.predictor_states = states
        else:
            if self.start:
                # prefix has no longer previously been seen. One deep copy to get started
                hypo.predictor_states = copy.deepcopy(hypo.predictor_states)
                self.set_predictor_states(hypo.predictor_states)
                self.start = False
            if hypo.word_to_consume is not None:
                self.consume(hypo.word_to_consume)
                hypo.word_to_consume = None
    
            ids, posterior, _ = self.apply_predictors()
            lprobabilities = adjusted_lprobabilities = utils.log_softmax(posterior, self.temperature)
            # assert not np.any(np.isnan(lprobabilities))
            self.dists.add_dist(prefix, ids, lprobabilities, self.get_predictor_states())

        ind = utils.gumbel_max_sample(adjusted_lprobabilities, seed)
        next_word = ids[ind]

        hypo.score += adjusted_lprobabilities[ind]
        hypo.score_breakdown.append(lprobabilities[ind])
        hypo.trgt_sentence += [next_word]
        hypo.word_to_consume = next_word
        hypo, score = self._expand_hypo(hypo, seed=seed)
        score += lprobabilities[ind] 
        self.dists.adjust(prefix, next_word, score)
        return hypo, score
         
    def reset_predictors(self, src_sentence):
        self.start = True
        for idx, (p, _) in enumerate(self.predictors):
            p.set_current_sen_id(self.current_sen_id)
            p.initialize(src_sentence)
        for h in self.heuristics:
            h.initialize(src_sentence)

    def samples_left(self):
        if len(self.full_hypos) == 0:
            return True
        if self.early_stopping and np.exp(self.covered_lprob) >= 1.0 - utils.MACHINE_EPS:
            return False
        start_hash = tuple()
        _, _, adjusted_lprobabilities, _ = self.dists.get(start_hash)
        return np.any(~np.isnan(adjusted_lprobabilities) > utils.NEG_INF )


class SworDecoder(Decoder):
    def __init__(self, decoder_args):
        """Creates a new SWOR decoder instance. The following values are
        fetched from `decoder_args`:
        
            nbest (int): number of desired samples. 
            temperature (float): temperature for shifting probability distributions
        
        Args:
            decoder_args (object): Decoder configuration passed through
                                   from the configuration API.
        """
        super(SworDecoder, self).__init__(decoder_args)
        self.nbest = decoder_args.nbest
        self.early_stopping = decoder_args.early_stopping
        assert not self.gumbel
        
    def decode(self, src_sentence):
        self.initialize_predictors(src_sentence)
        self.covered_lprob = utils.NEG_INF

        while len(self.full_hypos) < self.nbest and self.samples_left():
            if np.exp(self.covered_lprob) >= 1.0 - utils.MACHINE_EPS:
                logging.warn("Samples cover 100% of probability. Behavior beyond this point is undefined")
            self.reset_predictors(src_sentence)
            hypo = PartialHypothesis(self.get_predictor_states())
            hypo, score = self._expand_hypo(hypo, seed=len(self.full_hypos))
            self.add_full_hypo(hypo.generate_full_hypothesis())
            self.covered_lprob = utils.log_add(self.covered_lprob, score)
            
        logging.info("%d sentences covering %f probability" %(len(self.full_hypos), np.exp(self.covered_lprob)))
        return self.full_hypos

    def initialize_predictors(self, src_sentence):
        self.dists = MapDist()
        super().initialize_predictors(src_sentence)

    def _expand_hypo(self, hypo, seed=0):
        if hypo.get_last_word() == utils.EOS_ID or len(hypo) == self.max_len:
            return hypo, self.dists.marg(tuple(hypo.trgt_sentence))
        prefix = tuple(hypo.trgt_sentence)
        if prefix in self.dists:
            ids, lprobabilities, adjusted_lprobabilities, states = self.dists.get(prefix)
            hypo.predictor_states = states
        else:
            if self.start:
                # prefix has no longer previously been seen. One deep copy to get started
                hypo.predictor_states = copy.deepcopy(hypo.predictor_states)
                self.set_predictor_states(hypo.predictor_states)
                self.start = False
            if hypo.word_to_consume is not None:
                self.consume(hypo.word_to_consume)
                hypo.word_to_consume = None
            
            ids, posterior, _ = self.apply_predictors()
            marg = self.dists.marg(prefix)
            lprobabilities = adjusted_lprobabilities = utils.log_softmax(posterior, self.temperature) + marg
            self.dists.add_dist(prefix, ids, lprobabilities, self.get_predictor_states())

        ind = utils.gumbel_max_sample(adjusted_lprobabilities, seed)
        next_word = ids[ind]

        hypo.score += adjusted_lprobabilities[ind]
        hypo.score_breakdown.append(lprobabilities[ind])
        hypo.trgt_sentence += [next_word]
        hypo.word_to_consume = next_word
        hypo, final = self._expand_hypo(hypo, seed=seed)
        self.dists.adjust(prefix, next_word, final)
        return hypo, final
         
    def reset_predictors(self, src_sentence):
        self.start = True
        for idx, (p, _) in enumerate(self.predictors):
            p.set_current_sen_id(self.current_sen_id)
            p.initialize(src_sentence)
        for h in self.heuristics:
            h.initialize(src_sentence)

    def samples_left(self):
        if len(self.full_hypos) == 0:
            return True
        if self.early_stopping and np.exp(self.covered_lprob) >= 1.0 - utils.MACHINE_EPS:
            return False
        start_hash = tuple()
        _, _, adjusted_lprobabilities, _ = self.dists.get(start_hash)
        return np.any(~np.isnan(adjusted_lprobabilities) > utils.NEG_INF )


class MemEfficientSworDecoder(BasicSworDecoder):
    
    def __init__(self, decoder_args):
        """Creates a new SWOR decoder instance. The following values are
        fetched from `decoder_args`:
        
            nbest (int): number of desired samples. 
            temperature (float): temperature for shifting probability distributions
        
        Args:
            decoder_args (object): Decoder configuration passed through
                                   from the configuration API.
        """
        super(MemEfficientSworDecoder, self).__init__(decoder_args)

    
    def _expand_hypo(self, hypo, seed=0):
        if hypo.get_last_word() == utils.EOS_ID or len(hypo) == self.max_len:
            return hypo, 0.0
        if hypo.word_to_consume is not None:
            self.consume(hypo.word_to_consume)
            hypo.word_to_consume = None
        prefix = tuple(hypo.trgt_sentence)
        ids, posterior, _ = self.apply_predictors()
        lprobabilities = utils.log_softmax(posterior, self.temperature)
        adjusted_lprobabilities = self.adjust_probabilities(lprobabilities, prefix, ids)

        ind = utils.gumbel_max_sample(adjusted_lprobabilities, seed)
        next_word = ids[ind]

        hypo.score += adjusted_lprobabilities[ind]
        hypo.score_breakdown.append(lprobabilities[ind])
        hypo.trgt_sentence += [next_word]
        hypo.word_to_consume = next_word
        hypo, score = self._expand_hypo(hypo, seed=seed)
        score += lprobabilities[ind] 
        self.ids[prefix][next_word] = utils.log_add(score, self.ids[prefix][next_word])
        return hypo, score
        

    def adjust_probabilities(self, lprobabilities, hash_rep, ids):
        lprobabilities = np.copy(lprobabilities)
        for k, val in self.ids[hash_rep].items():
            ind = utils.binary_search(ids, k)
            lprobabilities[ind] = utils.log_minus(lprobabilities[ind], val)
        return lprobabilities

    def initialize_predictors(self, src_sentence):
        self.ids = defaultdict(lambda: defaultdict(lambda: utils.NEG_INF))
        self.src_sentence = src_sentence
        super().initialize_predictors(self.src_sentence)

    def samples_left(self):
        if len(self.full_hypos) == 0:
            return True
        if self.early_stopping and np.exp(self.covered_lprob) >= 1.0 - utils.MACHINE_EPS:
            return False
        self.reset_predictors(self.src_sentence)
        ids, posterior, _ = self.apply_predictors()
        start_hash = tuple()
        lprobabilities = utils.log_softmax(posterior, self.temperature)
        adjusted_lprobabilities = self.adjust_probabilities(lprobabilities, start_hash, ids)
        return np.any(~np.isnan(adjusted_lprobabilities) > utils.NEG_INF )


class MapDist(object):

    def __init__(self):
        self.dist_map = {}

    def __contains__(self, key):
        return tuple(key) in self.dist_map

    def add_dist(self, prefix, ids, dist, states):
        self.dist_map[prefix] = Dist(ids, dist, states)

    def adjust(self, prefix, next_word, val):
        self.dist_map[prefix].adjust(next_word, val)

    def get(self, prefix):
        return self.dist_map[prefix].values()

    def marg(self, prefix):
        if not prefix[:-1] in self.dist_map:
            return 0
        return self.dist_map[prefix[:-1]].get_current(prefix[-1])

    def set_zero_prob(self, prefix):
        self.dist_map[prefix[:-1]].set_null(prefix[-1])



class Dist(object):

    def __init__(self, ids, lprobabilities, predictor_states):
        self.ids = ids
        self.lprobabilities = lprobabilities
        self.adjustments = np.full_like(lprobabilities, utils.NEG_INF, dtype=np.float64)
        self.predictor_states = copy.deepcopy(predictor_states)
        self.adjusted_lprobabilities = np.copy(lprobabilities)
    
    def get_current(self, k):
        ind = utils.binary_search(self.ids, k)
        return self.adjusted_lprobabilities[ind]

    def adjust(self, k, val):
        ind = utils.binary_search(self.ids, k)
        self.adjustments[ind] = utils.log_add(self.adjustments[ind], val)
        self.adjusted_lprobabilities[ind] = utils.log_minus(self.lprobabilities[ind], self.adjustments[ind])

    def set_null(self, k):
        ind = utils.binary_search(self.ids, k)
        self.adjustments[ind] = self.lprobabilities[ind]
        self.adjusted_lprobabilities[ind] = utils.NEG_INF

    def values(self):
        return self.ids, self.lprobabilities, self.adjusted_lprobabilities, self.predictor_states


